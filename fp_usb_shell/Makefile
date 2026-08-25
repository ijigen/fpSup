# fp USB Shell v2
#
# The host tools need libusb-1.0.  The usual route is `brew install libusb`
# (macOS) or `apt install libusb-1.0-0-dev` (Debian/Ubuntu); this Makefile finds
# it through pkg-config, then the common Homebrew prefixes, and finally accepts
# an explicit path:
#
#     make LIBUSB=/path/to/a/libusb/install
#
CC     ?= cc
CFLAGS ?= -O2 -Wall -Wextra

PKG := $(shell command -v pkg-config 2>/dev/null)
ifneq ($(LIBUSB),)
  USB_CFLAGS := -I$(LIBUSB)
  USB_LDFLAGS := -L$(LIBUSB) -lusb-1.0 -Wl,-rpath,$(LIBUSB)
else ifneq ($(PKG),)
  ifeq ($(shell pkg-config --exists libusb-1.0 && echo yes),yes)
    USB_CFLAGS := $(shell pkg-config --cflags libusb-1.0)
    USB_LDFLAGS := $(shell pkg-config --libs libusb-1.0)
  endif
endif
ifeq ($(USB_LDFLAGS),)
  BREW := $(firstword $(wildcard /opt/homebrew/opt/libusb /usr/local/opt/libusb))
  ifneq ($(BREW),)
    USB_CFLAGS := -I$(BREW)/include/libusb-1.0
    USB_LDFLAGS := -L$(BREW)/lib -lusb-1.0
  else
    USB_CFLAGS := -I/usr/include/libusb-1.0
    USB_LDFLAGS := -lusb-1.0
  endif
endif

all: fpshd lsdesc autorun

fpshd: host/fpshd.c
	$(CC) $(CFLAGS) $< $(USB_CFLAGS) $(USB_LDFLAGS) -o $@

lsdesc: host/lsdesc.c
	$(CC) $(CFLAGS) $< $(USB_CFLAGS) $(USB_LDFLAGS) -o $@

autorun:
	./build_autorun.py

# make card CARD=/Volumes/<card name>
card: autorun
	@test -d "$(CARD)" || { echo "usage: make card CARD=/Volumes/<card name>"; exit 2; }
	cp autorun/AutoRun.txt "$(CARD)/AutoRun.txt"
	@sync 2>/dev/null; dot_clean -m "$(CARD)" 2>/dev/null; sync 2>/dev/null; true
	@cmp -s autorun/AutoRun.txt "$(CARD)/AutoRun.txt" \
		&& echo "card written and verified: $(CARD)/AutoRun.txt" \
		|| { echo "VERIFY FAILED"; exit 1; }

clean:
	rm -f fpshd lsdesc

.PHONY: all autorun card clean
