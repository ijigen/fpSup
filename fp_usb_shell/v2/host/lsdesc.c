/* lsdesc — print the camera's configuration descriptor exactly as the host sees it. */
#include <libusb.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *eptype(int t)
{
    static const char *n[] = {"Control", "Isoc", "Bulk", "Interrupt"};
    return n[t & 3];
}

int main(int argc, char **argv)
{
    uint16_t vid = argc > 1 ? (uint16_t)strtoul(argv[1], 0, 0) : 0x1003;
    uint16_t pid = argc > 2 ? (uint16_t)strtoul(argv[2], 0, 0) : 0xc432;

    libusb_context *ctx;
    if (libusb_init(&ctx)) { fprintf(stderr, "libusb_init failed\n"); return 1; }
    libusb_device_handle *h = libusb_open_device_with_vid_pid(ctx, vid, pid);
    if (!h) { fprintf(stderr, "device %04x:%04x not found\n", vid, pid); return 1; }

    libusb_device *dev = libusb_get_device(h);
    int speed = libusb_get_device_speed(dev);
    static const char *sp[] = {"unknown", "low", "full", "high", "super", "super+"};
    printf("device %04x:%04x   speed=%s\n", vid, pid, sp[speed < 6 ? speed : 0]);

    struct libusb_config_descriptor *cfg;
    if (libusb_get_active_config_descriptor(dev, &cfg)) {
        fprintf(stderr, "no active configuration\n"); return 1;
    }
    printf("config: bConfigurationValue=%d  wTotalLength=%d  bNumInterfaces=%d\n",
           cfg->bConfigurationValue, cfg->wTotalLength, cfg->bNumInterfaces);

    for (int i = 0; i < cfg->bNumInterfaces; i++)
        for (int a = 0; a < cfg->interface[i].num_altsetting; a++) {
            const struct libusb_interface_descriptor *id =
                &cfg->interface[i].altsetting[a];
            printf("  interface %d alt %d  class %02x/%02x/%02x  %d endpoints\n",
                   id->bInterfaceNumber, id->bAlternateSetting,
                   id->bInterfaceClass, id->bInterfaceSubClass,
                   id->bInterfaceProtocol, id->bNumEndpoints);
            for (int e = 0; e < id->bNumEndpoints; e++) {
                const struct libusb_endpoint_descriptor *ep = &id->endpoint[e];
                printf("    EP 0x%02X %-3s %-9s wMaxPacketSize=%-5d bInterval=%d",
                       ep->bEndpointAddress,
                       (ep->bEndpointAddress & 0x80) ? "IN" : "OUT",
                       eptype(ep->bmAttributes), ep->wMaxPacketSize, ep->bInterval);
                /* SuperSpeed companion, if the host kept it */
                for (int o = 0; o + 1 < ep->extra_length; ) {
                    const unsigned char *x = ep->extra + o;
                    if (x[1] == 0x30 && x[0] == 6)
                        printf("  [companion burst=%d bytesPerInterval=%d]",
                               x[2], x[4] | x[5] << 8);
                    o += x[0] ? x[0] : 1;
                }
                putchar('\n');
            }
        }

    libusb_free_config_descriptor(cfg);
    libusb_close(h);
    libusb_exit(ctx);
    return 0;
}
