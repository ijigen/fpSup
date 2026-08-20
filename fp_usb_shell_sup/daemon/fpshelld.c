#include <libusb.h>
#include <sys/time.h>
#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

#define VID 0x1003
#define PID 0xc432
#define EP_OUT 0x05
#define EP_IN 0x84
#define FRAME_SIZE 64
#define USB_OUT_SIZE 1024
#define PAYLOAD_SIZE 44

enum { CMD_PING = 1, CMD_ECHO = 2 };

typedef struct __attribute__((packed)) {
    uint8_t magic[4];
    uint8_t version, command;
    uint16_t flags;
    uint32_t sequence;
    uint16_t payload_length, status;
    uint32_t checksum;
    uint8_t payload[PAYLOAD_SIZE];
} fpsh_frame;

_Static_assert(sizeof(fpsh_frame) == FRAME_SIZE, "FPSH frame must be exactly 64 bytes");

typedef struct {
    libusb_context *usb;
    libusb_device_handle *camera;
    int mock;
    unsigned inter_wait_ms;
} backend;

static volatile sig_atomic_t running = 1;
static void stop_handler(int signal_number) { (void)signal_number; running = 0; }

static uint32_t crc32_bytes(const uint8_t *data, size_t size) {
    uint32_t crc = 0xffffffffu;
    for (size_t i = 0; i < size; ++i) {
        crc ^= data[i];
        for (int bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ (0xedb88320u & (uint32_t)-(int32_t)(crc & 1));
    }
    return ~crc;
}

static uint32_t frame_checksum(const fpsh_frame *frame) {
    fpsh_frame copy = *frame;
    copy.checksum = 0;
    return crc32_bytes((const uint8_t *)&copy, sizeof(copy));
}

static int write_all(int fd, const char *data) {
    size_t left = strlen(data);
    while (left) {
        ssize_t count = write(fd, data, left);
        if (count < 0) { if (errno == EINTR) continue; return -1; }
        data += count; left -= (size_t)count;
    }
    return 0;
}

static ssize_t read_line(int fd, char *buffer, size_t capacity) {
    size_t used = 0;
    while (used + 1 < capacity) {
        char byte;
        ssize_t count = read(fd, &byte, 1);
        if (count == 0) break;
        if (count < 0) { if (errno == EINTR) continue; return -1; }
        if (byte == '\n') break;
        if (byte != '\r') buffer[used++] = byte;
    }
    buffer[used] = '\0';
    return (ssize_t)used;
}

static int prepare_socket_path(const char *path) {
    struct stat status;
    if (lstat(path, &status) != 0) return errno == ENOENT ? 0 : -1;
    if (!S_ISSOCK(status.st_mode)) { errno = EEXIST; return -1; }

    int probe = socket(AF_UNIX, SOCK_STREAM, 0);
    if (probe < 0) return -1;
    struct sockaddr_un address = {0};
    address.sun_family = AF_UNIX;
    snprintf(address.sun_path, sizeof(address.sun_path), "%s", path);
    int connected = connect(probe, (struct sockaddr *)&address, sizeof(address));
    int saved_errno = errno;
    close(probe);
    if (connected == 0) { errno = EADDRINUSE; return -1; }
    if (saved_errno != ECONNREFUSED) { errno = saved_errno; return -1; }
    return unlink(path);
}

static int backend_open(backend *io, unsigned arm_wait) {
    if (io->mock) { fprintf(stderr, "mock transport ready\n"); return 0; }
    int rc = libusb_init(&io->usb);
    if (rc != 0) return rc;
    fprintf(stderr, "waiting for SIGMA fp vendor interface...\n");
    while (running) {
        io->camera = libusb_open_device_with_vid_pid(io->usb, VID, PID);
        if (io->camera && libusb_claim_interface(io->camera, 1) == 0) break;
        if (io->camera) libusb_close(io->camera);
        io->camera = NULL;
        usleep(250000);
    }
    if (!io->camera) return LIBUSB_ERROR_NO_DEVICE;
    fprintf(stderr, "interface claimed; camera arm wait %u seconds...\n", arm_wait);
    /* Do not clear either vendor endpoint during discovery.  The camera arms
     * its first EP05 TRB concurrently with interface claim; a startup
     * clear-halt can cancel that freshly queued transfer while the camera
     * worker remains blocked waiting for its completion.  Error recovery in
     * backend_exchange still clears a genuinely stalled endpoint. */
    sleep(arm_wait);
    /* The camera's verified context-4 initializer queues one zero-length IN
     * transfer before the persistent worker serves its first command.  Drain
     * that startup ZLP now, before any EP05 OUT exists, so it cannot be
     * mistaken for the 64-byte reply to sequence 0. */
    unsigned char startup_byte = 0;
    int startup_got = 0;
    int startup_rc = libusb_bulk_transfer(io->camera, EP_IN, &startup_byte, 1,
                                          &startup_got, 1000);
    if (startup_rc == 0 && startup_got == 0)
        fprintf(stderr, "drained camera startup ZLP\n");
    else if (startup_rc != LIBUSB_ERROR_TIMEOUT)
        fprintf(stderr, "startup IN drain: %s transferred=%d\n",
                libusb_error_name(startup_rc), startup_got);
    fprintf(stderr, "FPShell transport ready\n");
    return 0;
}

static void backend_close(backend *io) {
    if (io->camera) { libusb_release_interface(io->camera, 1); libusb_close(io->camera); }
    if (io->usb) libusb_exit(io->usb);
}

static int backend_exchange(backend *io, const uint8_t tx[USB_OUT_SIZE],
                            uint8_t rx[FRAME_SIZE], char *error, size_t error_size) {
    if (io->mock) { memcpy(rx, tx, FRAME_SIZE); return 0; }
    int transferred = 0;
    int rc = libusb_bulk_transfer(io->camera, EP_OUT, (unsigned char *)tx,
                                  USB_OUT_SIZE, &transferred, 60000);
    if (rc == LIBUSB_ERROR_PIPE || rc == LIBUSB_ERROR_IO) {
        /* EP05 stalled or not yet armed by the worker: clear halt and retry a few times. */
        for (int a = 0; a < 4 && (rc == LIBUSB_ERROR_PIPE || rc == LIBUSB_ERROR_IO); ++a) {
            libusb_clear_halt(io->camera, EP_OUT);
            usleep(200000);
            transferred = 0;
            rc = libusb_bulk_transfer(io->camera, EP_OUT, (unsigned char *)tx, USB_OUT_SIZE, &transferred, 60000);
        }
    }
    if (rc || transferred != USB_OUT_SIZE) {
        snprintf(error, error_size, "usb-out %s transferred=%d", libusb_error_name(rc), transferred);
        return -1;
    }
    transferred = 0;
    rc = libusb_bulk_transfer(io->camera, EP_IN, rx, FRAME_SIZE, &transferred, 60000);
    if (rc || transferred != FRAME_SIZE) {
        /* EP84 desynced (stall / stale residue from an abandoned raw grab). Recover:
         * clear halt, drain any leftover bytes, then re-issue the whole exchange once.
         * The worker re-arms EP84 continuously, so a clean 64B reply follows. */
        for (int attempt = 0; attempt < 3; ++attempt) {
            libusb_clear_halt(io->camera, EP_IN);
            unsigned char scratch[65536];
            int got, drained = 0;
            do { got = 0; libusb_bulk_transfer(io->camera, EP_IN, scratch, sizeof scratch, &got, 200); drained += got; } while (got > 0);
            libusb_clear_halt(io->camera, EP_OUT);
            int t = 0;
            if (libusb_bulk_transfer(io->camera, EP_OUT, (unsigned char *)tx, USB_OUT_SIZE, &t, 5000) || t != USB_OUT_SIZE) continue;
            transferred = 0;
            rc = libusb_bulk_transfer(io->camera, EP_IN, rx, FRAME_SIZE, &transferred, 60000);
            if (!rc && transferred == FRAME_SIZE) break;
        }
    }
    if (rc || transferred != FRAME_SIZE) {
        snprintf(error, error_size, "usb-in %s transferred=%d", libusb_error_name(rc), transferred);
        return -1;
    }
    if (io->inter_wait_ms) usleep(io->inter_wait_ms * 1000u);
    return 0;
}

static void build_frame(fpsh_frame *frame, uint8_t command, uint32_t sequence,
                        const char *payload) {
    memset(frame, 0, sizeof(*frame));
    memcpy(frame->magic, "FPSH", 4);
    frame->version = 1; frame->command = command; frame->sequence = sequence;
    size_t length = strlen(payload);
    if (length > PAYLOAD_SIZE) length = PAYLOAD_SIZE;
    frame->payload_length = (uint16_t)length;
    memcpy(frame->payload, payload, length);
    frame->checksum = frame_checksum(frame);
}

static int validate_frame(const fpsh_frame *frame, uint8_t command, uint32_t sequence,
                          char *error, size_t error_size) {
    if (memcmp(frame->magic, "FPSH", 4) || frame->version != 1) {
        snprintf(error, error_size, "bad-frame-header"); return -1;
    }
    if (frame->command != command || frame->sequence != sequence) {
        snprintf(error, error_size, "response-mismatch expected=%u got=%u", sequence, frame->sequence);
        return -1;
    }
    if (frame->payload_length > PAYLOAD_SIZE || frame->checksum != frame_checksum(frame)) {
        snprintf(error, error_size, "bad-frame-checksum-or-length"); return -1;
    }
    if (frame->status != 0) {
        snprintf(error, error_size, "camera-status=%u", frame->status); return -1;
    }
    return 0;
}

static int transact(backend *io, uint8_t command, const char *payload, uint32_t sequence,
                    char *response, size_t response_size) {
    uint8_t tx[USB_OUT_SIZE] = {0}, rx[FRAME_SIZE] = {0};
    build_frame((fpsh_frame *)tx, command, sequence, payload);
    char error[160];
    if (backend_exchange(io, tx, rx, error, sizeof(error))) {
        snprintf(response, response_size, "ERR sequence=%u %s\n", sequence, error); return -1;
    }
    const fpsh_frame *reply = (const fpsh_frame *)rx;
    if (validate_frame(reply, command, sequence, error, sizeof(error))) {
        snprintf(response, response_size, "ERR sequence=%u %s\n", sequence, error); return -1;
    }
    /* Binary-safe: hex-encode the payload (the old payload=%.*s truncated at NUL bytes,
       which broke every binary read the monitoring console needs). */
    unsigned plen = reply->payload_length;
    if (plen > PAYLOAD_SIZE) plen = PAYLOAD_SIZE;
    char hex[2 * PAYLOAD_SIZE + 1];
    static const char *H = "0123456789abcdef";
    for (unsigned i = 0; i < plen; i++) {
        hex[2*i]   = H[(reply->payload[i] >> 4) & 0xf];
        hex[2*i+1] = H[reply->payload[i] & 0xf];
    }
    hex[2*plen] = '\0';
    snprintf(response, response_size, "OK sequence=%u command=%s len=%u payload_hex=%s\n",
             sequence, command == CMD_PING ? "ping" : "echo", plen, hex);
    return 0;
}

static void usage(const char *program) {
    fprintf(stderr, "usage: %s [--mock] [--arm-wait SEC] [--inter-wait-ms MS] [--limit N] [--socket PATH]\n", program);
}

int main(int argc, char **argv) {
    const char *socket_path = getenv("FPSHELL_SOCKET");
    if (!socket_path || !socket_path[0]) socket_path = "/tmp/fpshell.sock";
    unsigned arm_wait = 32, limit = 4;
    backend io = {.inter_wait_ms = 2500};
    static const struct option options[] = {
        {"mock", no_argument, NULL, 'm'}, {"arm-wait", required_argument, NULL, 'a'},
        {"inter-wait-ms", required_argument, NULL, 'i'},
        {"limit", required_argument, NULL, 'l'}, {"socket", required_argument, NULL, 's'},
        {"help", no_argument, NULL, 'h'}, {NULL, 0, NULL, 0}
    };
    int option;
    while ((option = getopt_long(argc, argv, "ma:i:l:s:h", options, NULL)) != -1) {
        switch (option) {
            case 'm': io.mock = 1; break;
            case 'a': arm_wait = (unsigned)strtoul(optarg, NULL, 10); break;
            case 'i': io.inter_wait_ms = (unsigned)strtoul(optarg, NULL, 10); break;
            case 'l': limit = (unsigned)strtoul(optarg, NULL, 10); break;
            case 's': socket_path = optarg; break;
            default: usage(argv[0]); return option == 'h' ? 0 : 2;
        }
    }
    if (io.mock) io.inter_wait_ms = 0;
    char lock_path[sizeof(((struct sockaddr_un *)0)->sun_path) + 6];
    if (strlen(socket_path) >= sizeof(((struct sockaddr_un *)0)->sun_path) ||
        snprintf(lock_path, sizeof(lock_path), "%s.lock", socket_path) >= (int)sizeof(lock_path)) {
        usage(argv[0]); return 2;
    }

    struct sigaction action = {0};
    action.sa_handler = stop_handler; sigemptyset(&action.sa_mask);
    sigaction(SIGINT, &action, NULL); sigaction(SIGTERM, &action, NULL);
    struct sigaction ignore = {0};
    ignore.sa_handler = SIG_IGN; sigemptyset(&ignore.sa_mask);
    sigaction(SIGPIPE, &ignore, NULL);

    int lock_fd = open(lock_path, O_CREAT | O_RDWR | O_NOFOLLOW, S_IRUSR | S_IWUSR);
    if (lock_fd < 0 || flock(lock_fd, LOCK_EX | LOCK_NB) != 0) {
        perror("daemon lock unavailable");
        if (lock_fd >= 0) close(lock_fd);
        return 2;
    }

    int rc = backend_open(&io, arm_wait);
    if (rc) {
        fprintf(stderr, "transport open failed: %s\n", libusb_error_name(rc));
        close(lock_fd); backend_close(&io); return 2;
    }

    int server = socket(AF_UNIX, SOCK_STREAM, 0);
    if (server < 0) { close(lock_fd); backend_close(&io); return 2; }
    if (prepare_socket_path(socket_path) != 0) {
        perror("socket path unavailable"); close(server); close(lock_fd); backend_close(&io); return 2;
    }
    struct sockaddr_un address = {0};
    address.sun_family = AF_UNIX;
    snprintf(address.sun_path, sizeof(address.sun_path), "%s", socket_path);
    if (bind(server, (struct sockaddr *)&address, sizeof(address)) ||
        chmod(socket_path, S_IRUSR | S_IWUSR) || listen(server, 32)) {
        perror("socket setup"); close(server); unlink(socket_path); close(lock_fd); backend_close(&io); return 2;
    }

    uint32_t sequence = 0;
    while (running) {
        int client = accept(server, NULL, NULL);
        if (client < 0) { if (errno == EINTR) continue; break; }
        char request[1024], response[1200];
        ssize_t length = read_line(client, request, sizeof(request));
        if (length < 0) write_all(client, "ERR read\n");
        else if (!strcmp(request, "STATUS")) {
            snprintf(response, sizeof(response), "OK state=ready backend=%s used=%u limit=%u protocol=1 inter_wait_ms=%u\n",
                     io.mock ? "mock" : "usb", sequence, limit, io.inter_wait_ms); write_all(client, response);
        } else if (!strcmp(request, "INFO")) {
            write_all(client, "OK name=FPShell protocol=1 frame=64 payload=44 transport=EP05-EP84\n");
        } else if (!strcmp(request, "QUIT")) {
            write_all(client, "OK stopping\n"); running = 0;
        } else if (!strcmp(request, "PING") || !strncmp(request, "ECHO ", 5)) {
            if (limit && sequence >= limit) write_all(client, "ERR session-limit restart-camera\n");
            else {
                uint8_t command = request[0] == 'P' ? CMD_PING : CMD_ECHO;
                const char *payload = command == CMD_PING ? "PING" : request + 5;
                if (strlen(payload) > PAYLOAD_SIZE) write_all(client, "ERR payload-too-long max=44\n");
                else { transact(&io, command, payload, sequence++, response, sizeof(response)); write_all(client, response); }
            }
        } else if (!strncmp(request, "RAWREAD ", 8)) {
            long n = strtol(request + 8, NULL, 0);
            if (io.mock) write_all(client, "ERR mock\n");
            else if (n <= 0 || n > 32 * 1024 * 1024) write_all(client, "ERR bad-size max=32M\n");
            else {
                unsigned char *buf = malloc((size_t)n);
                if (!buf) write_all(client, "ERR nomem\n");
                else {
                    int got = 0; struct timeval a, b; gettimeofday(&a, NULL);
                    int rc = libusb_bulk_transfer(io.camera, EP_IN, buf, (int)n, &got, 15000);
                    gettimeofday(&b, NULL);
                    double ms = (b.tv_sec - a.tv_sec) * 1000.0 + (b.tv_usec - a.tv_usec) / 1000.0;
                    double mbps = ms > 0 ? got / (ms / 1000.0) / (1024.0 * 1024.0) : 0;
                    /* stats: count non-0xFF bytes + find the first 1MB slot that has real data */
                    long nonff = 0; int firstslot = -1;
                    for (int i = 0; i < got; i++) if (buf[i] != 0xff) {
                        nonff++; if (firstslot < 0) firstslot = i / (1024*1024);
                    }
                    FILE *f = fopen("/tmp/rawread.bin", "wb");
                    if (f) { fwrite(buf, 1, got, f); fclose(f); }
                    snprintf(response, sizeof(response),
                        "OK rc=%d bytes=%d ms=%.2f MBps=%.1f nonff=%ld firstslot=%d saved=/tmp/rawread.bin\n",
                        rc, got, ms, mbps, nonff, firstslot);
                    write_all(client, response); free(buf);
                }
            }
        } else if (!strncmp(request, "RAWGRAB ", 8)) {
            /* RAWGRAB <hexaddr> <declen>: send worker cmd "raw <addr> <len>" (EP05), then bulk-IN raw */
            unsigned long addr = 0; long n = 0;
            if (sscanf(request + 8, "%lx %ld", &addr, &n) != 2 || n <= 0 || n > 0xFF0000)
                write_all(client, "ERR usage: RAWGRAB <hexaddr> <declen<=16MB>\n");
            else if (io.mock) write_all(client, "ERR mock\n");
            else {
                char payload[64]; snprintf(payload, sizeof(payload), "raw 0x%lx %ld", addr, n);
                uint8_t tx[USB_OUT_SIZE] = {0};
                build_frame((fpsh_frame *)tx, CMD_ECHO, sequence++, payload);
                int t = 0; int rc = libusb_bulk_transfer(io.camera, EP_OUT, tx, USB_OUT_SIZE, &t, 5000);
                if (rc || t != USB_OUT_SIZE) {
                    snprintf(response, sizeof(response), "ERR cmd-out %s t=%d\n", libusb_error_name(rc), t);
                    write_all(client, response);
                } else {
                    unsigned char *buf = malloc((size_t)n);
                    if (!buf) write_all(client, "ERR nomem\n");
                    else {
                        int got = 0; struct timeval a, b; gettimeofday(&a, NULL);
                        rc = libusb_bulk_transfer(io.camera, EP_IN, buf, (int)n, &got, 15000);
                        gettimeofday(&b, NULL);
                        double ms = (b.tv_sec - a.tv_sec) * 1000.0 + (b.tv_usec - a.tv_usec) / 1000.0;
                        double mbps = ms > 0 ? got / (ms / 1000.0) / (1024.0 * 1024.0) : 0;
                        long nonff = 0; int fs = -1;
                        for (int i = 0; i < got; i++) if (buf[i] != 0xff) { nonff++; if (fs < 0) fs = i; }
                        FILE *f = fopen("/tmp/rawgrab.bin", "wb"); if (f) { fwrite(buf, 1, got, f); fclose(f); }
                        /* re-sync EP84 so a following shell command resumes clean. On a CLEAN grab
                         * (rc==0, full length) the worker delivered exactly one TRB with no residue,
                         * so just give it a brief moment to re-arm — fast path for back-to-back grabs
                         * (the live viewer). Only on a short/errored grab do the heavy clear_halt+drain. */
                        if (rc == 0 && got == (int)n) {
                            usleep(80000);   /* reliable settle: worker re-arms EP05 OUT before next grab */
                        } else {
                            libusb_clear_halt(io.camera, EP_IN);
                            { unsigned char s[65536]; int g; do { g = 0; libusb_bulk_transfer(io.camera, EP_IN, s, sizeof s, &g, 150); } while (g > 0); }
                            usleep(80000);
                        }
                        snprintf(response, sizeof(response),
                            "OK addr=0x%lx rc=%d bytes=%d ms=%.2f MBps=%.1f nonff=%ld firstnonff=%d saved=/tmp/rawgrab.bin\n",
                            addr, rc, got, ms, mbps, nonff, fs);
                        write_all(client, response); free(buf);
                    }
                }
            }
        } else write_all(client, "ERR unknown-command\n");
        close(client);
    }
    close(server); unlink(socket_path); backend_close(&io); close(lock_fd); return 0;
}
