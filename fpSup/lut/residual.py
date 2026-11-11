"""Offline CPU residual fitting from paired native-output/target RGB samples.

No assumed CEQ/ISP pixel formula, camera access, deployment or frame-rate claim.
Training inputs must be measured after native processing in a declared RGB
domain. Outputs may exceed that domain; this module does not hide clipping.
"""
from dataclasses import dataclass
import numpy as np


def _rgb(values):
    values = np.asarray(values, dtype=np.float64)
    if values.ndim < 1 or values.shape[-1] != 3 or not np.isfinite(values).all():
        raise ValueError('finite RGB triples required')
    return values


def _domain(domain):
    domain = np.asarray(domain, dtype=np.float64)
    if domain.shape != (2, 3) or not np.isfinite(domain).all() or np.any(domain[1] <= domain[0]):
        raise ValueError('explicit increasing RGB domain required')
    return domain


def _vertices(rgb, size, domain):
    y = _rgb(rgb).reshape(-1, 3)
    low, high = _domain(domain)
    if np.any(y < low) or np.any(y > high):
        raise ValueError('native output outside residual domain; refusing implicit clamp')
    pos = (y - low) / (high - low) * (size - 1)
    base = np.minimum(np.floor(pos).astype(np.int64), size - 2)
    fractions = pos - base
    order = np.argsort(-fractions, axis=1, kind='stable')
    f = np.take_along_axis(fractions, order, axis=1)
    weights = np.column_stack((1 - f[:, 0], f[:, 0] - f[:, 1], f[:, 1] - f[:, 2], f[:, 2]))
    indices = np.empty((len(y), 4), dtype=np.int64)
    rows = np.arange(len(y))
    for vertex in range(4):
        if vertex:
            base[rows, order[:, vertex - 1]] += 1
        r, g, b = base.T
        indices[:, vertex] = (b * size + g) * size + r
    return indices, weights


def _forward(nodes, indices, weights):
    return np.sum(nodes[indices] * weights[:, :, None], axis=1)


def _transpose(values, indices, weights, count):
    result = np.empty((count, 3), dtype=np.float64)
    flat = indices.ravel()
    for channel in range(3):
        result[:, channel] = np.bincount(flat,
            weights=(values[:, channel, None] * weights).ravel(), minlength=count)
    return result


def _laplacian(nodes, size):
    grid = nodes.reshape(size, size, size, 3)
    out = np.zeros_like(grid)
    for axis in range(3):
        a, b = [slice(None)] * 4, [slice(None)] * 4
        a[axis], b[axis] = slice(0, -1), slice(1, None)
        delta = grid[tuple(a)] - grid[tuple(b)]
        out[tuple(a)] += delta
        out[tuple(b)] -= delta
    return out.reshape(-1, 3)


def collision_floor(native, target):
    """Exact output collisions imply irrecoverable information for output-only correction."""
    native, target = _rgb(native).reshape(-1, 3), _rgb(target).reshape(-1, 3)
    if native.shape != target.shape or not len(native):
        raise ValueError('nonempty paired RGB samples required')
    _, inverse, counts = np.unique(native, axis=0, return_inverse=True, return_counts=True)
    means = np.zeros((len(counts), 3))
    np.add.at(means, inverse, target)
    means /= counts[:, None]
    error = target - means[inverse]
    minimum = np.full_like(means, np.inf)
    maximum = np.full_like(means, -np.inf)
    np.minimum.at(minimum, inverse, target)
    np.maximum.at(maximum, inverse, target)
    conflicts = np.any(minimum != maximum, axis=1)
    error[~conflicts[inverse]] = 0
    return {'rgb_rmse_lower_bound': float(np.sqrt(np.mean(error ** 2))),
            'duplicate_output_groups': int(np.sum(counts > 1)),
            'conflicting_output_groups': int(np.sum(conflicts)),
            'near_collisions_included': False}


def error_metrics(result, target):
    result, target = _rgb(result), _rgb(target)
    if result.shape != target.shape or not result.size:
        raise ValueError('nonempty corresponding RGB arrays required')
    errors = result - target
    maximum_channel = np.max(np.abs(errors), axis=-1)
    return {'rgb_rmse': float(np.sqrt(np.mean(errors ** 2))),
            'p95_max_channel_error': float(np.percentile(maximum_channel, 95)),
            'max_channel_error': float(np.max(maximum_channel)),
            'metric': 'declared RGB encoding, not perceptual DeltaE'}


@dataclass(frozen=True)
class ResidualAffine:
    coefficients: np.ndarray
    domain: np.ndarray

    def __post_init__(self):
        coefficients = np.asarray(self.coefficients, dtype=np.float32).copy()
        if coefficients.shape != (4, 3) or not np.isfinite(coefficients).all():
            raise ValueError('finite 4x3 correction coefficients required')
        domain = _domain(self.domain).copy()
        coefficients.flags.writeable = domain.flags.writeable = False
        object.__setattr__(self, 'coefficients', coefficients)
        object.__setattr__(self, 'domain', domain)

    def apply(self, native):
        native = _rgb(native)
        low, high = self.domain
        if np.any(native < low) or np.any(native > high):
            raise ValueError('native output outside residual domain; refusing implicit clamp')
        return native + native @ self.coefficients[:3] + self.coefficients[3]

    def summary(self):
        return {'kind': 'affine', 'float32_coefficient_bytes': self.coefficients.nbytes,
                'domain': self.domain.tolist(), 'output_clamped': False,
                'camera_runtime_verified': False}

    @classmethod
    def fit(cls, native, target, domain=((0, 0, 0), (1, 1, 1))):
        native, target = _rgb(native), _rgb(target)
        if native.shape != target.shape or native.ndim != 2 or len(native) < 4:
            raise ValueError('at least four paired RGB samples required')
        low, high = _domain(domain)
        if np.any(native < low) or np.any(native > high):
            raise ValueError('native output outside residual domain; refusing implicit clamp')
        design = np.column_stack((native, np.ones(len(native))))
        coefficients, _, rank, _ = np.linalg.lstsq(design, target - native, rcond=None)
        if rank != 4:
            raise ValueError('rank-deficient colour samples cannot calibrate affine correction')
        model = cls(coefficients, domain)
        return model, {**model.summary(), 'training_samples': len(native),
                       'training_error': error_metrics(model.apply(native), target),
                       'collision_floor': collision_floor(native, target),
                       'held_out_validation_required': True}


@dataclass(frozen=True)
class ResidualGrid:
    table: np.ndarray
    domain: np.ndarray

    def __post_init__(self):
        table = np.asarray(self.table, dtype=np.float32).copy()
        size = table.shape[0] if table.ndim else 0
        if size not in (5, 9, 17) or table.shape != (size, size, size, 3) or not np.isfinite(table).all():
            raise ValueError('finite 5/9/17 cubed residual RGB grid required')
        domain = _domain(self.domain).copy()
        table.flags.writeable = domain.flags.writeable = False
        object.__setattr__(self, 'table', table)
        object.__setattr__(self, 'domain', domain)

    def apply(self, native):
        native = _rgb(native)
        indices, weights = _vertices(native, len(self.table), self.domain)
        correction = _forward(self.table.reshape(-1, 3), indices, weights)
        return native + correction.reshape(native.shape)

    def summary(self):
        return {'grid_size': len(self.table), 'float32_table_bytes': self.table.nbytes,
                'domain': self.domain.tolist(),
                'max_abs_node_correction': float(np.max(np.abs(self.table))),
                'vertices_per_pixel': 4, 'output_clamped': False,
                'camera_runtime_verified': False}

    @classmethod
    def fit(cls, native, target, size=9, domain=((0, 0, 0), (1, 1, 1)),
            ridge=1e-8, smoothness=1e-6, tolerance=1e-8, max_iterations=400):
        native, target = _rgb(native), _rgb(target)
        if native.shape != target.shape or native.ndim != 2 or not len(native):
            raise ValueError('nonempty Nx3 paired RGB samples required')
        if size not in (5, 9, 17):
            raise ValueError('supported residual sizes are 5, 9, 17')
        if (not np.isfinite([ridge, smoothness, tolerance]).all() or ridge <= 0
                or smoothness < 0 or tolerance <= 0 or max_iterations < 1):
            raise ValueError('invalid fit limits')
        count = size ** 3
        indices, weights = _vertices(native, size, domain)
        delta = target - native
        rhs = _transpose(delta, indices, weights, count) / len(native)
        def multiply(nodes):
            return (_transpose(_forward(nodes, indices, weights), indices, weights, count)
                    / len(native) + ridge * nodes + smoothness * _laplacian(nodes, size))
        diagonal = np.bincount(indices.ravel(), weights=(weights ** 2).ravel(), minlength=count) / len(native)
        degree = np.zeros((size, size, size))
        for axis in range(3):
            a, b = [slice(None)] * 3, [slice(None)] * 3
            a[axis], b[axis] = slice(0, -1), slice(1, None)
            degree[tuple(a)] += 1
            degree[tuple(b)] += 1
        diagonal += ridge + smoothness * degree.ravel()
        nodes = np.zeros((count, 3))
        residual = rhs.copy()
        z = residual / diagonal[:, None]
        direction = z.copy()
        rz = np.sum(residual * z, axis=0)
        threshold = tolerance * np.maximum(np.linalg.norm(rhs, axis=0), 1e-12)
        converged = np.linalg.norm(residual, axis=0) <= threshold
        iteration = 0
        for iteration in range(1, max_iterations + 1):
            if converged.all():
                break
            direction[:, converged] = 0
            product = multiply(direction)
            denominator = np.sum(direction * product, axis=0)
            alpha = np.divide(rz, denominator, out=np.zeros(3), where=~converged)
            nodes += direction * alpha
            residual -= product * alpha
            converged = np.linalg.norm(residual, axis=0) <= threshold
            z = residual / diagonal[:, None]
            next_rz = np.sum(residual * z, axis=0)
            beta = np.divide(next_rz, rz, out=np.zeros(3), where=~converged)
            direction = z + direction * beta
            rz = next_rz
        if not converged.all() or not np.isfinite(nodes).all():
            raise RuntimeError('bounded residual solver did not converge')
        model = cls(nodes.reshape(size, size, size, 3), domain)
        coverage = np.bincount(indices.ravel(), weights=weights.ravel(), minlength=count)
        report = {**model.summary(), 'training_samples': len(native), 'iterations': iteration,
                  'observed_nodes': int(np.sum(coverage > 0)), 'total_nodes': count,
                  'training_error': error_metrics(model.apply(native), target),
                  'collision_floor': collision_floor(native, target),
                  'held_out_validation_required': True,
                  'training_kind': 'caller supplied pairs; provenance not inferred'}
        return model, report
