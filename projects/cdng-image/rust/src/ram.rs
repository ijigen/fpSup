use std::{
    collections::VecDeque,
    sync::{Condvar, Mutex},
};

struct State<T> {
    items: VecDeque<(T, usize)>,
    bytes: usize,
    peak: usize,
    closed: bool,
}
pub(crate) struct Queue<T> {
    state: Mutex<State<T>>,
    ready: Condvar,
    space: Condvar,
    limit: usize,
}
pub(crate) struct Producer<'a, T>(&'a Queue<T>);
impl<T> Drop for Producer<'_, T> {
    fn drop(&mut self) {
        self.0.finish();
    }
}
impl<T> Queue<T> {
    pub fn producer(&self) -> Producer<'_, T> {
        Producer(self)
    }
    pub fn new(limit: usize) -> Self {
        Self {
            state: Mutex::new(State {
                items: VecDeque::new(),
                bytes: 0,
                peak: 0,
                closed: false,
            }),
            ready: Condvar::new(),
            space: Condvar::new(),
            limit,
        }
    }
    pub fn push(&self, value: T, bytes: usize) -> bool {
        let mut state = self.state.lock().unwrap();
        while !state.closed
            && !state.items.is_empty()
            && (state.bytes.saturating_add(bytes) > self.limit || state.items.len() >= 4096)
        {
            state = self.space.wait(state).unwrap();
        }
        if state.closed {
            return false;
        }
        state.bytes = state.bytes.saturating_add(bytes);
        state.peak = state.peak.max(state.bytes);
        state.items.push_back((value, bytes));
        self.ready.notify_one();
        true
    }
    pub fn pop(&self) -> Option<T> {
        let mut state = self.state.lock().unwrap();
        loop {
            if let Some((value, bytes)) = state.items.pop_front() {
                state.bytes -= bytes;
                self.space.notify_all();
                return Some(value);
            }
            if state.closed {
                return None;
            }
            state = self.ready.wait(state).unwrap();
        }
    }
    pub fn finish(&self) {
        let mut s = self.state.lock().unwrap();
        s.closed = true;
        self.ready.notify_all();
        self.space.notify_all();
    }
    pub fn abort(&self) {
        let mut s = self.state.lock().unwrap();
        s.closed = true;
        s.items.clear();
        s.bytes = 0;
        self.ready.notify_all();
        self.space.notify_all();
    }
    pub fn stats(&self) -> (usize, usize) {
        let s = self.state.lock().unwrap();
        (s.bytes, s.peak)
    }
}

#[allow(unreachable_code)]
pub(crate) fn default_budget() -> usize {
    #[cfg(target_os = "macos")]
    {
        unsafe extern "C" {
            fn cdng_ram_budget() -> u64;
        }
        // Read-only native memory statistics; no GPU/device access is needed.
        return (unsafe { cdng_ram_budget() } as usize).clamp(64 << 20, 8usize << 30);
    }
    #[cfg(target_os = "windows")]
    {
        #[repr(C)]
        struct Memory {
            length: u32,
            load: u32,
            total: u64,
            available: u64,
            total_page: u64,
            available_page: u64,
            total_virtual: u64,
            available_virtual: u64,
            available_extended: u64,
        }
        #[link(name = "kernel32")]
        unsafe extern "system" {
            fn GlobalMemoryStatusEx(memory: *mut Memory) -> i32;
        }
        let mut memory = Memory {
            length: std::mem::size_of::<Memory>() as u32,
            load: 0,
            total: 0,
            available: 0,
            total_page: 0,
            available_page: 0,
            total_virtual: 0,
            available_virtual: 0,
            available_extended: 0,
        };
        if unsafe { GlobalMemoryStatusEx(&mut memory) } != 0 {
            return ((memory.total / 8).min(memory.available / 4) as usize)
                .clamp(64 << 20, 8usize << 30);
        }
    }
    256 << 20
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn byte_limit_and_abort_release_blocked_producers() {
        let q = Queue::new(10);
        assert!(q.push(1, 6));
        assert_eq!(q.stats(), (6, 6));
        std::thread::scope(|s| {
            let worker = s.spawn(|| q.push(2, 6));
            assert_eq!(q.pop(), Some(1));
            assert!(worker.join().unwrap());
        });
        assert_eq!(q.stats(), (6, 6));
        std::thread::scope(|s| {
            let worker = s.spawn(|| q.push(3, 6));
            q.abort();
            assert!(!worker.join().unwrap());
        });
        assert_eq!(q.pop(), None);
        assert_eq!(q.stats(), (0, 6));
        let q = Queue::new(0);
        assert!(q.push(4, 100));
        q.finish();
        assert_eq!(q.pop(), Some(4));
        assert_eq!(q.pop(), None);
    }
    #[test]
    fn producer_panic_wakes_the_writer() {
        let q = Queue::<u8>::new(10);
        std::thread::scope(|s| {
            let worker = s.spawn(|| {
                let _completion = q.producer();
                panic!("simulated producer failure");
            });
            assert_eq!(q.pop(), None);
            assert!(worker.join().is_err());
        });
    }
}
