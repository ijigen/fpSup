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
#define FPSHD_VERSION "2.0.0"
#define MAX_REPLY    8192
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
    if (!g_cam) return -1;
    libusb_set_auto_detach_kernel_driver(g_cam, 1);
    if (libusb_claim_interface(g_cam, IFACE) != 0) {
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
static void drain_in(void)
{
    unsigned char junk[FRAME_SIZE];
    for (int i = 0; i < 16; i++) {
        int moved = 0;
        if (libusb_bulk_transfer(g_cam, EP_IN, junk, FRAME_SIZE, &moved, 5) != 0)
            break;
        if (moved == 0)
            break;
    }
}


static int exchange(uint8_t command, const char *arg, char *out, size_t outcap)
{
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
    txf->checksum = crc32(txbuf, FRAME_SIZE);
    fpsh_frame tx = *txf;                       /* header copy for reply matching */

    int moved = 0;
    int rc = libusb_bulk_transfer(g_cam, EP_OUT, txbuf, (int)txlen,
                                  &moved, g_timeout);
    if (rc != 0 || moved != (int)txlen) {
        if (rc == LIBUSB_ERROR_NO_DEVICE) cam_close();
        else if (rc == LIBUSB_ERROR_PIPE) libusb_clear_halt(g_cam, EP_OUT);
        return -1;
    }

    size_t used = 0;
    for (int frame = 0; frame < MAX_REPLY / PAYLOAD_SIZE + 1; frame++) {
        fpsh_frame rx;
        moved = 0;
        rc = libusb_bulk_transfer(g_cam, EP_IN, (unsigned char *)&rx, FRAME_SIZE,
                                  &moved, g_timeout);
        if (rc != 0 || moved != FRAME_SIZE) {
            if (rc == LIBUSB_ERROR_NO_DEVICE) { cam_close(); return -1; }
            if (rc == LIBUSB_ERROR_PIPE) libusb_clear_halt(g_cam, EP_IN);
            drain_in();
            return -1;
        }
        if (memcmp(rx.magic, "FPSH", 4) || rx.version != 1) { drain_in(); return -1; }
        uint32_t want = rx.checksum;
        rx.checksum = 0;
        if (crc32((const uint8_t *)&rx, FRAME_SIZE) != want) { drain_in(); return -1; }
        if (rx.sequence != tx.sequence) { drain_in(); return -1; }

        uint16_t n = rx.payload_length;
        if (n > PAYLOAD_SIZE) n = PAYLOAD_SIZE;
        if (used + n < outcap) { memcpy(out + used, rx.payload, n); used += n; }
        if (!(rx.flags & 1)) break;          /* last frame */
    }
    out[used] = 0;
    return (int)used;
}

static void write_line(int fd, const char *s)
{
    size_t n = strlen(s);
    while (n) { ssize_t w = write(fd, s, n); if (w <= 0) return; s += w; n -= (size_t)w; }
}

/* newline/backslash-escape so one reply is always exactly one socket line */
static void write_escaped(int fd, const char *s)
{
    char buf[MAX_REPLY * 2 + 8]; size_t o = 0;
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

    char line[MAX_REPLY], reply[MAX_REPLY];
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
            int r = exchange(CMD_PING, NULL, reply, sizeof reply);
            if (r < 0) write_line(c, "ERR ping\n");
            else { char s[64]; snprintf(s, sizeof s, "OK pong seq=%u\n", g_seq); write_line(c, s); }
            close(c); continue;
        }
        if (!strncmp(line, "SHL ", 4)) {
            char cmd[CMD_MAX];
            snprintf(cmd, sizeof cmd, "shl %s", line + 4);
            int r = exchange(CMD_SHL, cmd, reply, sizeof reply);
            if (r < 0) write_line(c, "ERR shl\n");
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
