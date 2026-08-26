/* fpshd — host side of the camera USB shell.
 *
 * The camera runs its stock PTP gadget with the class handler removed, so the
 * bulk pipes belong to us and the interface reports itself as vendor-specific.
 *
 *   transport : interface 0, EP 0x01 OUT (commands) / EP 0x82 IN (replies)
 *   frame     : FPSH v1, 64 bytes; a long command spills past byte 64 of the
 *               same OUT transfer, because the camera reads it as a string
 *   replies   : may be chunked — flags bit 0 means another frame follows
 *
 * Socket protocol, one line in and one line out:
 *   PING            -> OK pong seq=<n>
 *   SHL <line>      -> OK <output, with newlines escaped as \n>
 *   STATUS          -> OK name=fpshd ...
 *   QUIT            -> OK bye
 */
#include <libusb.h>
#include <errno.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#define FRAME_SIZE   64
#define PAYLOAD_SIZE 44
#define IFACE        0
#define EP_OUT       0x01
#define EP_IN        0x82
#define FPSHD_VERSION "3.0.0"
/* Was 16384, the size of the shell's capture buffer -- because everything used
 * to be copied through it. The worker can now point its TRB at wherever the
 * answer already is, and a TRB carries a 24-bit length, so a reply can be
 * megabytes. Kept well under that: these are buffers, not a promise. */
#define MAX_REPLY    (16 * 1024 * 1024)   /* one TRB's 24-bit length */
#define CMD_LINE_MAX 16384
#define USB_OUT_SIZE 1024
#define CMD_MAX      512

enum { CMD_PING = 1, CMD_SHL = 3 };

typedef struct __attribute__((packed)) {
    uint8_t  magic[4];
    uint8_t  version, command;
    uint16_t flags;
    uint32_t sequence;
    uint16_t payload_length, status;
    uint32_t checksum;
    uint8_t  payload[PAYLOAD_SIZE];
} fpsh_frame;
_Static_assert(sizeof(fpsh_frame) == FRAME_SIZE, "frame must be 64 bytes");

static uint16_t g_vid = 0x1003, g_pid = 0xc432;
/* A reply that has not arrived in this long is lost, not slow: the transport
 * drops whole commands, roughly one in ten, and waiting five seconds for one of
 * them turned a 550 character `mem get` into an average of 774 ms. The caller
 * retries, which costs a fifth of a second instead of five. Commands that
 * genuinely take longer -- an SD write is up to 692 ms -- report through their
 * own status word, so a timeout there is not a failure either. */
static unsigned g_timeout = 200;
/* Two hundred milliseconds is right for a command that has to open a file, and
 * badly wrong for one that answers in under two. A reply goes missing every few
 * dozen chunks -- retrying costs nothing, waiting for the timeout costs more
 * than the whole rest of the read -- so a caller that knows its command is fast
 * can say so per request with a TMO prefix. */
static unsigned g_req_timeout = 0;
#define TMO (g_req_timeout ? g_req_timeout : g_timeout)
static int g_was_bulk;      /* the last exchange came back as one raw block */
/* Replies under 128 bytes come back as frames rather than one block, and a
 * line-based socket cannot carry those bytes as they are -- a NUL ends the
 * string, a newline ends the line. Big replies were already hex-encoded because
 * they arrive as a block; HEX says to do it for a small one too, so a caller
 * reading memory gets the same thing back whatever the length. */
static int g_want_hex;
/* "ERR shl" says a transfer failed and nothing else, so every theory about why
 * had to be guessed at. libusb already knows. */
static char g_why[96];
static libusb_context      *g_usb;
static libusb_device_handle*g_cam;
static uint32_t             g_seq;
static volatile sig_atomic_t g_stop;

static uint32_t crc32(const uint8_t *p, size_t n)
{
    uint32_t c = 0xFFFFFFFFu;
    for (size_t i = 0; i < n; i++) {
        c ^= p[i];
        for (int b = 0; b < 8; b++) c = (c >> 1) ^ (0xEDB88320u & -(c & 1));
    }
    return ~c;
}

static int cam_open(void)
{
    if (g_cam) return 0;
    g_cam = libusb_open_device_with_vid_pid(g_usb, g_vid, g_pid);
    if (!g_cam) {
        snprintf(g_why, sizeof g_why, "open %04x:%04x failed", g_vid, g_pid);
        return -1;
    }
    libusb_set_auto_detach_kernel_driver(g_cam, 1);
    int rc = libusb_claim_interface(g_cam, IFACE);
    if (rc != 0) {
        snprintf(g_why, sizeof g_why, "claim iface %d rc=%d(%s)",
                 IFACE, rc, libusb_error_name(rc));
        libusb_close(g_cam); g_cam = NULL; return -1;
    }
    return 0;
}

static void cam_close(void)
{
    if (!g_cam) return;
    libusb_release_interface(g_cam, IFACE);
    libusb_close(g_cam);
    g_cam = NULL;
}

/* Send one command frame, collect the (possibly chunked) reply into out.
 * Returns reply length, or -1. */
/* Read and discard anything still sitting on the IN pipe.
 *
 * Every failed exchange used to leave its late reply there, and the next command
 * would read that instead of its own, mismatch the sequence, and leave one
 * behind in turn. The failure rate climbed from 3% to 45% over a session that
 * way -- not a transport fault at all, but a queue nobody emptied. */
/* Clear whatever the camera has already sent and nobody collected.
 *
 * This used to read sixteen times into a 64-byte buffer, which clears a
 * kilobyte. A reply is up to sixteen of those, so a request that timed out left
 * most of its block in the pipe, and the retry was answered with it. Asking for
 * less than the endpoint is holding is itself an error, so the buffer has to be
 * at least one whole reply.
 *
 * Nothing here is about corruption. USB bulk carries its own CRC and retries in
 * hardware; every wrong byte was a right byte from the wrong request. */
static void drain_in(void)
{
    static unsigned char junk[CMD_LINE_MAX];
    for (int i = 0; i < 8; i++) {
        int moved = 0;
        /* Short. Outlasting the camera's own three hundred milliseconds was
         * the obvious thing -- a block abandoned here may still be on its way,
         * and leaving it is leaving exactly what this is for. But a miss then
         * costs the host's timeout plus this, better than half a second, and at
         * five per cent of two thousand chunks that was most of a minute on a
         * 31 MB file: every measurement of "the link is slow" was this.
         *
         * A late block that slips past is not a problem any more. Each one
         * carries the address it was read from, so the next read sees it is
         * somebody else's answer, drops it and asks again -- a few milliseconds
         * instead of five hundred. */
        int rc = libusb_bulk_transfer(g_cam, EP_IN, junk, sizeof junk,
                                      &moved, 20);
        if (rc == LIBUSB_ERROR_PIPE) { libusb_clear_halt(g_cam, EP_IN); continue; }
        if (rc == LIBUSB_ERROR_OVERFLOW) continue;
        if (rc != 0 || moved == 0) break;
    }
}


static int exchange(uint8_t command, const char *arg, char *out, size_t outcap,
                    int raw_len)
{
    g_why[0] = 0;
    if (cam_open() != 0) return -1;

    /* The camera arms a 1024-byte OUT TRB and reads the payload as a NUL-terminated
     * string, so a command longer than the 44-byte payload field simply spills past
     * offset 64 in the same transfer.  The CRC still covers only the first 64 bytes,
     * which is what the camera and this daemon agree on. */
    size_t arglen = arg ? strlen(arg) : 0;
    if (arglen > CMD_MAX - 1) arglen = CMD_MAX - 1;
    size_t txlen = 20 + arglen + 1;
    if (txlen < FRAME_SIZE) txlen = FRAME_SIZE;
    txlen = (txlen + 3) & ~3u;

    unsigned char txbuf[USB_OUT_SIZE];
    memset(txbuf, 0, txlen);
    fpsh_frame *txf = (fpsh_frame *)txbuf;
    memcpy(txf->magic, "FPSH", 4);
    txf->version  = 1;
    txf->command  = command;
    txf->sequence = ++g_seq;
    txf->payload_length = (uint16_t)arglen;
    if (arglen) memcpy(txf->payload, arg, arglen);
    if (raw_len > 0) txf->flags = 1;    /* the reply is raw, and this long */
    txf->checksum = crc32(txbuf, FRAME_SIZE);
    fpsh_frame tx = *txf;                       /* header copy for reply matching */

    g_was_bulk = 0;
    int moved = 0;
    int rc = libusb_bulk_transfer(g_cam, EP_OUT, txbuf, (int)txlen,
                                  &moved, TMO);
    if (rc != 0 || moved != (int)txlen) {
        snprintf(g_why, sizeof g_why, "cmd rc=%d(%s) moved=%d/%d",
                 rc, libusb_error_name(rc), moved, (int)txlen);
        if (rc == LIBUSB_ERROR_NO_DEVICE) cam_close();
        else if (rc == LIBUSB_ERROR_PIPE) libusb_clear_halt(g_cam, EP_OUT);
        return -1;
    }

    size_t used = 0;

    /* Told the length, so there is nothing to negotiate: one transfer, no header
     * frame, no window in which the host can outrun the camera's arming. */
    if (raw_len > 0) {
        if ((size_t)raw_len > outcap) {
        snprintf(g_why, sizeof g_why, "raw_len %d over cap %zu", raw_len, outcap);
        return -1;
    }
        moved = 0;
        rc = libusb_bulk_transfer(g_cam, EP_IN, (unsigned char *)out,
                                  raw_len, &moved, TMO);
        if (rc != 0 || moved != raw_len) {
            snprintf(g_why, sizeof g_why, "block rc=%d(%s) moved=%d/%d",
                     rc, libusb_error_name(rc), moved, raw_len);
            if (rc == LIBUSB_ERROR_NO_DEVICE) { cam_close(); return -1; }
            if (rc == LIBUSB_ERROR_PIPE) libusb_clear_halt(g_cam, EP_IN);
            drain_in();
            return -1;
        }
        g_was_bulk = 1;
        return moved;
    }

    int skipped = 0;
    for (int frame = 0; frame < CMD_LINE_MAX / PAYLOAD_SIZE + 1; frame++) {
        fpsh_frame rx;
        moved = 0;
        rc = libusb_bulk_transfer(g_cam, EP_IN, (unsigned char *)&rx, FRAME_SIZE,
                                  &moved, TMO);
        if (rc != 0 || moved != FRAME_SIZE) {
            snprintf(g_why, sizeof g_why, "frame%d rc=%d(%s) moved=%d/%d",
                     frame, rc, libusb_error_name(rc), moved, FRAME_SIZE);
            if (rc == LIBUSB_ERROR_NO_DEVICE) { cam_close(); return -1; }
            if (rc == LIBUSB_ERROR_PIPE) libusb_clear_halt(g_cam, EP_IN);
            drain_in();
            return -1;
        }
        if (memcmp(rx.magic, "FPSH", 4) || rx.version != 1) {
            snprintf(g_why, sizeof g_why, "bad magic %02x%02x%02x%02x ver %u",
                     rx.magic[0], rx.magic[1], rx.magic[2], rx.magic[3], rx.version);
            drain_in(); return -1; }
        uint32_t want = rx.checksum;
        rx.checksum = 0;
        if (crc32((const uint8_t *)&rx, FRAME_SIZE) != want) {
            snprintf(g_why, sizeof g_why, "frame crc");
            drain_in(); return -1; }
        /* A reply from an earlier command, arriving after that command gave
         * up waiting for it. Every frame says which request it belongs to, so
         * there is no need to guess and no need to throw the pipe away: read
         * past it -- including the block it announces, or the next read starts
         * in the middle of one -- and carry on looking for the answer to this
         * request.
         *
         * Draining instead was what made a single slow reply poison everything
         * after it. The drain cleared a kilobyte of a reply up to sixteen long,
         * the remainder answered the next request, and the two stayed one apart
         * until it looked like the endpoint had died. */
        if (rx.sequence != tx.sequence) {
            if (rx.flags & 2) {
                static unsigned char skip[CMD_LINE_MAX];
                uint32_t n = rx.payload_length;
                if (n > sizeof skip) { drain_in(); return -1; }
                int got = 0;
                libusb_bulk_transfer(g_cam, EP_IN, skip, (int)n, &got, TMO);
            }
            if (++skipped > 32) {
                snprintf(g_why, sizeof g_why,
                         "%d stale frames, last seq %u wanted %u",
                         skipped, rx.sequence, tx.sequence);
                drain_in(); return -1;
            }
            frame--;                    /* this one did not count */
            continue;
        }

        /* flags bit 1: the header is describing a block that follows in one
         * transfer, rather than carrying 44 bytes itself. Forty-four bytes per
         * 64-byte frame is 1.1% of what this endpoint can move -- it is bulk,
         * 1024-byte packets, burst 3 -- and reading a 250 KB file that way took
         * eighty thousand round trips. The block's CRC-32 rides in the header so
         * it is still checked. */
        if (rx.flags & 2) {
            g_was_bulk = 1;
            uint32_t n = rx.payload_length, want_block;
            memcpy(&want_block, rx.payload, 4);
            if (n >= outcap) { drain_in(); return -1; }
            moved = 0;
            rc = libusb_bulk_transfer(g_cam, EP_IN, (unsigned char *)out,
                                      (int)n, &moved, TMO);
            if (rc != 0 || moved != (int)n) {
                if (rc == LIBUSB_ERROR_PIPE) libusb_clear_halt(g_cam, EP_IN);
                drain_in();
                return -1;
            }
            if (crc32((const uint8_t *)out, n) != want_block) { drain_in(); return -1; }
            used = n;
            break;
        }

        uint16_t n = rx.payload_length;
        if (n > PAYLOAD_SIZE) n = PAYLOAD_SIZE;
        if (used + n < outcap) { memcpy(out + used, rx.payload, n); used += n; }
        if (!(rx.flags & 1)) break;          /* last frame */
    }
    out[used] = 0;
    return (int)used;
}

static void write_all(int fd, const char *buf, size_t n)
{
    while (n) {
        ssize_t w = write(fd, buf, n);
        if (w <= 0) return;
        buf += w; n -= (size_t)w;
    }
}


static void write_line(int fd, const char *s)
{
    size_t n = strlen(s);
    while (n) { ssize_t w = write(fd, s, n); if (w <= 0) return; s += w; n -= (size_t)w; }
}

/* newline/backslash-escape so one reply is always exactly one socket line */
static void write_escaped(int fd, const char *s)
{
    static char buf[CMD_LINE_MAX * 2 + 8]; size_t o = 0;
    for (; *s && o < sizeof buf - 3; s++) {
        if (*s == '\n')      { buf[o++] = '\\'; buf[o++] = 'n'; }
        else if (*s == '\r') { }
        else if (*s == '\\') { buf[o++] = '\\'; buf[o++] = '\\'; }
        else                  buf[o++] = *s;
    }
    buf[o++] = '\n'; buf[o] = 0;
    write_line(fd, buf);
}

static void on_signal(int s) { (void)s; g_stop = 1; }

int main(int argc, char **argv)
{
    const char *sock_path = "/tmp/fpshd.sock";
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--socket") && i + 1 < argc)      sock_path = argv[++i];
        else if (!strcmp(argv[i], "--vid") && i + 1 < argc)    g_vid = (uint16_t)strtoul(argv[++i], 0, 0);
        else if (!strcmp(argv[i], "--pid") && i + 1 < argc)    g_pid = (uint16_t)strtoul(argv[++i], 0, 0);
        else if (!strcmp(argv[i], "--timeout") && i + 1 < argc) g_timeout = (unsigned)strtoul(argv[++i], 0, 0);
        else { fprintf(stderr, "usage: %s [--socket P] [--vid V] [--pid P] [--timeout MS]\n", argv[0]); return 2; }
    }

    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
    signal(SIGPIPE, SIG_IGN);

    if (libusb_init(&g_usb) != 0) { fprintf(stderr, "libusb_init failed\n"); return 1; }

    unlink(sock_path);
    int srv = socket(AF_UNIX, SOCK_STREAM, 0);
    struct sockaddr_un a; memset(&a, 0, sizeof a);
    a.sun_family = AF_UNIX;
    snprintf(a.sun_path, sizeof a.sun_path, "%s", sock_path);
    if (bind(srv, (struct sockaddr *)&a, sizeof a) || listen(srv, 8)) {
        fprintf(stderr, "bind/listen %s: %s\n", sock_path, strerror(errno)); return 1;
    }
    fprintf(stderr, "fpshd " FPSHD_VERSION ": %s  vid=%04x pid=%04x  iface=%d "
            "ep_out=%02x ep_in=%02x\n",
            sock_path, g_vid, g_pid, IFACE, EP_OUT, EP_IN);

    /* static, not automatic: a four-megabyte reply does not go on the stack. */
    static char line[CMD_LINE_MAX];
    static char reply[MAX_REPLY];
    while (!g_stop) {
        int c = accept(srv, NULL, NULL);
        if (c < 0) { if (errno == EINTR) continue; break; }
        ssize_t n = read(c, line, sizeof line - 1);
        if (n <= 0) { close(c); continue; }
        line[n] = 0;
        char *nl = strpbrk(line, "\r\n"); if (nl) *nl = 0;

        if (!strcmp(line, "QUIT")) { write_line(c, "OK bye\n"); close(c); g_stop = 1; break; }
        if (!strcmp(line, "STATUS")) {
            char s[160];
            snprintf(s, sizeof s, "OK name=fpshd version=" FPSHD_VERSION " protocol=1 frame=64 "
                     "payload=44 transport=EP01-EP82 iface=0 camera=%s seq=%u\n",
                     g_cam ? "open" : "closed", g_seq);
            write_line(c, s); close(c); continue;
        }
        if (!strcmp(line, "PING")) {
            int r = exchange(CMD_PING, NULL, reply, sizeof reply, 0);
            if (r < 0) write_line(c, "ERR ping\n");
            else { char s[64]; snprintf(s, sizeof s, "OK pong seq=%u\n", g_seq); write_line(c, s); }
            close(c); continue;
        }
        /* TMO <ms> <line>: this one command answers fast, so do not spend a
         * fifth of a second finding out that its reply went missing. */
        g_req_timeout = 0;
        g_want_hex = 0;
        if (!strncmp(line, "HEX ", 4)) {
            g_want_hex = 1;
            memmove(line, line + 4, strlen(line + 4) + 1);
        }
        if (!strncmp(line, "TMO ", 4)) {
            char *rest;
            unsigned ms = (unsigned)strtoul(line + 4, &rest, 10);
            while (*rest == ' ') rest++;
            if (ms) g_req_timeout = ms;
            memmove(line, rest, strlen(rest) + 1);
        }

        /* BULK <n> <line>: the caller already knows how many bytes come back. */
        int raw_len = 0;
        char *body = line;
        if (!strncmp(line, "BULK ", 5)) {
            raw_len = (int)strtol(line + 5, &body, 10);
            while (*body == ' ') body++;
            memmove(line + 4, body, strlen(body) + 1);
            memcpy(line, "SHL ", 4);
        }
        if (!strncmp(line, "SHL ", 4)) {
            char cmd[CMD_MAX];
            snprintf(cmd, sizeof cmd, "shl %s", line + 4);
            int r = exchange(CMD_SHL, cmd, reply, sizeof reply, raw_len);
            if (r < 0) {
                char e[128];
                snprintf(e, sizeof e, "ERR shl %s\n",
                         g_why[0] ? g_why : "no detail");
                write_line(c, e);
            }
            else if (g_was_bulk || g_want_hex) {
                /* A raw block: the camera put the bytes in the reply buffer
                 * itself rather than printing them, so they are not text and
                 * cannot go down a line-based socket as they are. Hex here
                 * rather than on the camera -- doubling the volume matters over
                 * USB and costs nothing over a unix socket. */
                static const char hex[] = "0123456789ABCDEF";
                char *line = malloc((size_t)r * 2 + 8);
                if (!line) { write_line(c, "ERR mem\n"); close(c); continue; }
                memcpy(line, "OKX ", 4);
                for (int i = 0; i < r; i++) {
                    line[4 + i * 2]     = hex[(unsigned char)reply[i] >> 4];
                    line[4 + i * 2 + 1] = hex[(unsigned char)reply[i] & 15];
                }
                line[4 + r * 2] = '\n';
                write_all(c, line, (size_t)r * 2 + 5);
                free(line);
            }
            else { write_line(c, "OK "); write_escaped(c, reply); }
            close(c); continue;
        }
        write_line(c, "ERR unknown\n");
        close(c);
    }

    cam_close();
    close(srv);
    unlink(sock_path);
    libusb_exit(g_usb);
    return 0;
}
