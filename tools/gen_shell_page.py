#!/usr/bin/env python3
"""Generate fpSup/explainers/shell-commands.html from docs/SHELL_COMMANDS.md.

The command list is parsed rather than transcribed: 77 entries with their
handler addresses and the usage text that was asked from a live camera.
Re-run this after editing the markdown.
"""
import re, html, pathlib

FPSUP = pathlib.Path(__file__).resolve().parent.parent
SRC = FPSUP / 'docs/SHELL_COMMANDS.md'
OUT = FPSUP / 'explainers/shell-commands.html'

GROUPS = {
    'memory':   ('Memory, CPU and RTOS',
                 'mem memmgr ddr dbg drcv runtime status sys analyzer ts tsd tkos '
                 'port pmctest ppmgr reboot rebootf poff pw_save echo # help log'),
    'bus':      ('Bus, device and firmware',
                 'i2c prom device dfi detect model version versioncheck setconfig '
                 'setting fwup cam adc battery'),
    'imaging':  ('Imaging, ISP and recording',
                 'imager adj optic pic wb still movrec rec recstate rectmlg play qr'),
    'exposure': ('Exposure, AF and lens',
                 'menu ae af lens levelgauge imu'),
    'io':       ('I/O, UI and storage',
                 'strb extstrb fl led usb uart gps audio key touch ui gui display '
                 'evf_bri event ptp sdcard dir mkdir time ctrl sg3'),
}
# Badges. "nonvol" is the only one that can outlive a battery pull.
NONVOL = {'prom', 'fwup'}
RESET  = {'reboot', 'rebootf', 'poff', 'pw_save'}
WRITES = {'mem', 'i2c', 'port', 'menu', 'setconfig', 'setting', 'adj', 'imager'}


def parse(md: str):
    body = md.split('## The 77 commands / 77 條指令', 1)[1]
    parts = re.split(r'\n### `([^`]+)`([^\n]*)\n', body)
    out = []
    for i in range(1, len(parts), 3):
        name, blk = parts[i], parts[i + 2]
        h = re.search(r'`handler (0x[0-9A-Fa-f]+)`', blk)
        ni = re.search(r'\*\*Not invoked — ([^*]+)\*\*', blk)
        nou = re.search(r'\*No usage text([^*]*)\*', blk)
        usage = re.search(r'```\n(.*?)\n```', blk, re.S)
        reason = None
        if ni:                      # "english / 中文" -> keep the english half
            reason = ni.group(1).split(' / ')[0].strip()
        out.append(dict(name=name, handler=h.group(1) if h else '',
                        reason=reason, nousage=bool(nou),
                        usage=usage.group(1).rstrip() if usage else None))
    return out


def card(c, gid):
    n = c['name']
    badges = []
    if n in NONVOL:
        badges.append('<span class="tag nonvol">non-volatile</span>')
    if n in RESET:
        badges.append('<span class="tag reset">resets</span>')
    if n in WRITES:
        badges.append('<span class="tag writes">writes</span>')
    if c['reason']:
        badges.append('<span class="tag notrun">not run</span>')
    disp = 'comment' if n == '#' else n
    # data-text drives the search box: name + usage + skip reason
    hay = ' '.join(filter(None, [n, c['usage'] or '', c['reason'] or ''])).lower()
    s = ['<details class="cmd" data-g="%s" data-n="%s" data-text="%s"%s>'
         % (gid, html.escape(n, True), html.escape(hay, True),
            ' data-notrun="1"' if c['reason'] else '')]
    s.append('<summary><code class="nm">%s</code>'
             '<span class="hnd">%s</span>%s</summary>'
             % (html.escape(disp), c['handler'], ''.join(badges)))
    if c['usage']:
        s.append('<pre>%s</pre>' % html.escape(c['usage']))
    elif c['reason']:
        s.append('<p class="skip"><b>Not run.</b> %s &mdash; the usage text below it '
                 'would have to be asked on a camera that can afford the '
                 'consequence.</p>' % html.escape(c['reason']))
    else:
        s.append('<p class="skip">No usage text: it takes no arguments, or prints '
                 'nothing.</p>')
    s.append('</details>')
    return '\n'.join(s)


def main():
    cmds = parse(SRC.read_text(encoding='utf-8'))
    by = {c['name']: c for c in cmds}
    assert len(cmds) == 77, f'expected 77 commands, parsed {len(cmds)}'

    n_usage = sum(1 for c in cmds if c['usage'])
    n_skip = sum(1 for c in cmds if c['reason'])

    sections = []
    for gid, (label, names) in GROUPS.items():
        lst = [by[n] for n in names.split()]
        sections.append(
            '<section class="grp" data-g="%s">\n<h3>%s <span class="cnt">%d</span></h3>\n'
            '<div class="cmds">\n%s\n</div>\n</section>'
            % (gid, html.escape(label), len(lst),
               '\n'.join(card(c, gid) for c in lst)))

    page = TEMPLATE.replace('{{SECTIONS}}', '\n'.join(sections))
    page = page.replace('{{N_USAGE}}', str(n_usage)).replace('{{N_SKIP}}', str(n_skip))
    OUT.write_text(page, encoding='utf-8')
    print(f'wrote {OUT}  ({len(page):,} bytes)  '
          f'{len(cmds)} commands, {n_usage} with usage, {n_skip} not run')


TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>The firmware shell &mdash; fpSup</title>
<meta name="description" content="The SIGMA fp carries a factory debug shell with 77 commands and no permission gate. All 77 listed with their handler addresses and the firmware's own usage text, asked from a live camera.">

<meta property="og:type" content="article">
<meta property="og:url" content="https://ijigen.github.io/fpSup/explainers/shell-commands.html">
<meta property="og:title" content="SIGMA fp: the firmware shell">
<meta property="og:description" content="77 commands, run from a text file on the SD card with no permission gate. The complete list, with the firmware's own usage text.">
<meta property="og:image" content="https://ijigen.github.io/fpSup/assets/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">

<link rel="icon" href="../assets/favicon.ico" sizes="any">
<link rel="icon" href="../assets/favicon-32.png" type="image/png" sizes="32x32">
<link rel="apple-touch-icon" href="../assets/apple-touch-icon.png">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<link rel="stylesheet" href="../assets/site.css">
<style>
/* ---- the primitive table gets a little more room than a plain .scroll ---- */
table.prim td:first-child{white-space:nowrap}
table.prim code{color:var(--sig); font-weight:600}

/* ---- search + filter bar ------------------------------------------------ */
.filter{position:sticky; top:0; z-index:5; background:var(--paper);
  padding:12px 0 11px; margin:16px 0 0; border-bottom:1px solid var(--line)}
.filter input[type=search]{width:100%; font-family:var(--mono); font-size:.9rem;
  padding:9px 12px; border:1px solid var(--line); border-radius:3px;
  background:var(--panel); color:var(--ink); -webkit-appearance:none}
.filter input[type=search]:focus-visible{outline:2px solid var(--sig); outline-offset:1px}
.chipbar{display:flex; flex-wrap:wrap; gap:6px; margin-top:10px; align-items:center}
.chipbar button{font-family:var(--mono); font-size:.71rem; letter-spacing:.03em;
  padding:5px 10px; border:1px solid var(--line); border-radius:3px;
  background:var(--panel); color:var(--dim); cursor:pointer;
  transition:border-color .12s, color .12s, background .12s}
.chipbar button:hover{border-color:var(--sig); color:var(--ink)}
.chipbar button[aria-pressed="true"]{border-color:var(--sig); color:var(--sig);
  background:var(--sig-soft); font-weight:600}
.chipbar button:focus-visible{outline:2px solid var(--sig); outline-offset:2px}
.chipbar .count{margin-left:auto; font-family:var(--mono); font-size:.72rem;
  color:var(--dim); white-space:nowrap}

/* ---- command cards ------------------------------------------------------ */
.grp{margin-top:26px}
.grp h3{display:flex; align-items:baseline; gap:9px; margin:0 0 9px;
  font-family:var(--mono); font-size:.76rem; font-weight:600;
  text-transform:uppercase; letter-spacing:.08em; color:var(--dim)}
.grp h3 .cnt{font-size:.7rem; font-weight:400; opacity:.75}
.cmds{display:grid; gap:1px; background:var(--line); border:1px solid var(--line);
  border-radius:3px; overflow:hidden}
details.cmd{background:var(--panel)}
details.cmd > summary{display:flex; align-items:center; gap:10px; flex-wrap:wrap;
  padding:11px 14px; cursor:pointer; list-style:none; transition:background .12s}
details.cmd > summary::-webkit-details-marker{display:none}
details.cmd > summary:hover{background:var(--sig-soft)}
details.cmd > summary:focus-visible{outline:2px solid var(--sig); outline-offset:-2px}
details.cmd .nm{font-family:var(--mono); font-size:.93rem; font-weight:600;
  color:var(--sig)}
details.cmd .hnd{font-family:var(--mono); font-size:.72rem; color:var(--dim)}
details[open].cmd > summary{background:var(--sig-soft)}
details.cmd pre{margin:0; padding:13px 15px 15px; overflow-x:auto;
  font-family:var(--mono); font-size:.76rem; line-height:1.55; color:var(--ink);
  background:var(--paper); border-top:1px solid var(--line); white-space:pre}
details.cmd .skip{margin:0; padding:12px 15px 14px; font-size:.86rem;
  color:var(--dim); background:var(--paper); border-top:1px solid var(--line)}
details.cmd .skip b{color:var(--ink)}
.tag{font-family:var(--mono); font-size:.64rem; letter-spacing:.04em;
  border:1px solid var(--line); border-radius:3px; padding:2px 6px;
  color:var(--dim); white-space:nowrap}
.tag.notrun{opacity:.8}
.tag.writes{border-color:var(--warn); color:var(--warn); background:var(--warn-soft)}
.tag.reset{border-color:var(--warn); color:var(--warn)}
.tag.nonvol{border-color:var(--sig); color:var(--sig); background:var(--sig-soft);
  font-weight:600}
.empty{display:none; font-size:.9rem; color:var(--dim); padding:24px 2px}
.empty.on{display:block}
</style>
</head>
<body>

<a class="back" href="../research.html">&larr; Firmware research</a>

<header class="hero">
  <div class="hero-text">
    <h1>The firmware shell</h1>
    <p class="lede">The fp carries a factory debug shell with 77 commands. A text
    file on the SD card runs them at boot, and nothing asks for a password. This is
    all 77, with the firmware's own usage text where a camera could safely be asked
    for it.</p>
    <ul class="chips">
      <li><b>77</b> commands</li>
      <li><b>{{N_USAGE}}</b> asked on a live camera</li>
      <li><b>no</b> permission gate</li>
    </ul>
  </div>
</header>

<div class="facts">
  <dl>
    <dt>Where it is</dt>
    <dd>A table at <code>0xC0BAC14C</code>: 77 entries of
    <code>{ char name[0x14]; void *handler; }</code>, stride <code>0x18</code>,
    NULL-terminated. The dispatcher <code>FUN_c03d9c20</code> splits the line on
    spaces, matches the first token against that table, and calls the handler.</dd>
    <dt>Where the text came from</dt>
    <dd>Every usage block below was <b>printed by the camera itself</b> over the USB
    shell. It is the firmware's own help, not a reconstruction, which is why the
    formatting and the typos are uneven.</dd>
    <dt>What was not run</dt>
    <dd>{{N_SKIP}} commands could reboot the camera, write non-volatile storage,
    drive hardware, change live settings, or drop the USB channel carrying the
    question. They are listed with what they are and why they were skipped.</dd>
  </dl>
</div>

<h2>Three ways in</h2>

<p>The same 77 commands, reached three different ways:</p>

<div class="scroll">
<table>
  <thead><tr><th>route</th><th>how</th><th>when</th></tr></thead>
  <tbody>
    <tr><td>AutoRun</td>
        <td><code>_AutoRun.txt</code> on the SD card, one command per line</td>
        <td>at boot, before most of the camera is up</td></tr>
    <tr><td>USB shell</td>
        <td><a href="https://github.com/ijigen/fpSup/tree/main/fp_usb_shell">fp USB Shell</a>
        forwards a line with <code>shl &lt;cmd&gt;</code></td>
        <td>any time the camera is on</td></tr>
    <tr><td>UART</td>
        <td>the interactive prompt the shell was built for</td>
        <td>needs the pads inside the body</td></tr>
  </tbody>
</table>
</div>

<p class="note">AutoRun is the one that matters, and it is worth being plain about
why: <b>there is no permission gate</b>. A file on a memory card runs arbitrary
commands from this list at boot. That is the whole basis of everything else on this
site &mdash; open gate, the gyro logger, the USB shell all ride on it.</p>

<h2>The write primitives</h2>

<p>Most of the 77 report something. Five of them change something, and those five
are the reason the rest of this project is possible:</p>

<div class="scroll">
<table class="prim">
  <thead><tr><th>command</th><th>what it reaches</th></tr></thead>
  <tbody>
    <tr><td><code>mem set [addr] [data]</code></td>
        <td><b>Any 32-bit write, anywhere.</b> The handler checks 4-byte alignment
        and nothing else &mdash; no range check. That covers DRAM, SRAM and the
        SoC's peripheral registers at <code>0x3xxxxxxx</code>.</td></tr>
    <tr><td><code>i2c w [dev] [reg] [data]</code></td>
        <td>Writes the I&sup2;C bus: the image sensor, the PMIC, anything on it.
        <code>i2c list</code> names the devices.</td></tr>
    <tr><td><code>prom write [id] [src] [size]</code></td>
        <td><b>Non-volatile.</b> See the warning below.</td></tr>
    <tr><td><code>port set [name] high|low</code></td>
        <td>Drives a named GPIO pin.</td></tr>
    <tr><td><code>menu [Setter] [value]</code></td>
        <td>Writes a live camera setting directly &mdash; about 65 setters covering
        ISO, shutter, aperture, drive, AE and AF.</td></tr>
  </tbody>
</table>
</div>

<p><code>mem set</code> is the one that changes what is possible. An arbitrary poke
available at boot, with no gate in front of it, is what turns a closed camera into
one you can modify.</p>

<h2>Safety</h2>

<p>Three tiers, and they are genuinely different:</p>

<ol class="steps">
  <li>
    <h3>Reading is safe</h3>
    <p><code>mem get</code>, <code>mem save</code>, <code>dir</code>,
    <code>version</code>, the RTOS introspection commands &mdash; none of these
    change anything. Note that a read of an <em>unmapped</em> address can still
    hang the camera, so a scan of a guessed range is not a read-only operation in
    practice.</p>
  </li>
  <li>
    <h3>A RAM or register poke is, at worst, a reboot</h3>
    <p>Everything <code>mem set</code> and <code>port set</code> touch is volatile.
    A bad write freezes or resets the camera; pulling the battery gets it back. This
    is the tier all of this project's products live in.</p>
  </li>
  <li>
    <h3><code>prom write</code> outlives the battery</h3>
    <p>This is the only tier that can leave the camera permanently worse.</p>
  </li>
</ol>

<div class="warn"><b>Two specific reasons to leave <code>prom write</code> alone.</b>
Its size argument is rounded <em>up</em> to a 128 KB boundary
(<code>(size + 0x1FFFF) &amp; 0xFFFE0000</code>) &mdash; a NAND erase-block &mdash;
so writing a handful of bytes rewrites a whole block. And the <code>id</code>
argument is just an index into a device registry whose mapping to physical parts
<b>has not been worked out</b>. Together that means writing an unknown amount to an
unidentified device. Back everything up with <code>prom readfile</code> first, and
prefer not to go there at all.</div>

<h2>All 77 commands</h2>

<p>Search matches the command name and the usage text. Handler addresses are
Ver.5.02.</p>

<div class="filter">
  <input type="search" id="q" placeholder="Search names and usage text&hellip;"
         autocomplete="off" spellcheck="false" aria-label="Search commands">
  <div class="chipbar" id="chips">
    <button type="button" data-f="all" aria-pressed="true">all</button>
    <button type="button" data-f="memory" aria-pressed="false">memory &amp; RTOS</button>
    <button type="button" data-f="bus" aria-pressed="false">bus &amp; device</button>
    <button type="button" data-f="imaging" aria-pressed="false">imaging</button>
    <button type="button" data-f="exposure" aria-pressed="false">exposure &amp; AF</button>
    <button type="button" data-f="io" aria-pressed="false">I/O &amp; storage</button>
    <button type="button" data-f="notrun" aria-pressed="false">not run</button>
    <span class="count" id="count">77 of 77</span>
  </div>
</div>

{{SECTIONS}}

<p class="empty" id="empty">Nothing matches that.</p>

<h2>What is available at boot</h2>

<p>AutoRun fires early, which cuts both ways:</p>

<div class="scroll">
<table>
  <thead><tr><th>state</th><th>commands</th></tr></thead>
  <tbody>
    <tr><td>ready immediately</td>
        <td>anything that is pure CPU and memory: <code>mem</code>,
        <code>port</code>, <code>ddr</code>, <code>reboot</code>, the RTOS
        introspection. <b>The most useful one, <code>mem set</code>, is in this
        group.</b></td></tr>
    <tr><td>needs its driver up</td>
        <td><code>i2c</code>, <code>prom</code>, <code>imager</code>,
        <code>adj</code>, <code>imu</code>, <code>pic</code>, <code>optic</code>,
        <code>play</code>, <code>qr</code>, <code>rec</code>, <code>movrec</code>,
        <code>menu</code>. Run too early these no-op, or act on an uninitialised
        state.</td></tr>
  </tbody>
</table>
</div>

<p class="note">The exact init order per subsystem versus the moment AutoRun fires
has not been traced command by command. In practice the products here work around
it by doing the memory writes at boot and deferring anything driver-shaped until
the camera has reached a known state.</p>

<h2>Still open</h2>

<ul>
  <li>The <code>prom</code> device-id to physical-part mapping
  (<code>FUN_c0041f78</code> holds the registry). Until that is read out,
  <code>prom write</code> has no safe target.</li>
  <li>Which <code>i2c list</code> name is the image sensor and which is the PMIC.</li>
  <li>The per-subsystem init order against AutoRun's exact timing &mdash; whether a
  given hardware command is safe at the moment it fires.</li>
  <li><code>sg3</code> is undocumented and was not run; nobody knows what it is.</li>
  <li>There is no obvious recording time-limit command. <code>rectmlg</code> only
  stores a tag string, so any limit is probably a <code>menu</code> or
  <code>setconfig</code> value rather than a command of its own.</li>
</ul>

<h2>Sources</h2>

<p>The command table, the dispatcher and the handler addresses were read out of the
Ver.5.02 image. The usage text was asked from a camera over the USB shell, with a
capture sink pushed onto the shell's own output stack so the firmware's
<code>printf</code> came back over USB instead of going to the UART pads. The
working documents are
<a href="https://github.com/ijigen/fpSup/blob/main/docs/SHELL_COMMANDS.md">SHELL_COMMANDS</a>
and
<a href="https://github.com/ijigen/fpSup/blob/main/docs/SHELL_CAPABILITIES.md">SHELL_CAPABILITIES</a>,
and this page is generated from the first of them by
<a href="https://github.com/ijigen/fpSup/blob/main/tools/gen_shell_page.py">tools/gen_shell_page.py</a>.</p>

<footer>
  <p><a href="../research.html">Firmware research</a> &middot;
  <a href="../">fpSup</a> &middot;
  <a href="https://discord.gg/XeFK5zNZpT">Discord</a> &middot;
  <a href="https://github.com/ijigen/fpSup">Repository</a></p>
</footer>

<script>
(function(){
  var q = document.getElementById('q');
  var chips = document.getElementById('chips');
  var count = document.getElementById('count');
  var empty = document.getElementById('empty');
  if(!q || !chips) return;
  var cards = [].slice.call(document.querySelectorAll('details.cmd'));
  var groups = [].slice.call(document.querySelectorAll('section.grp'));
  var filter = 'all';

  function apply(){
    var term = q.value.trim().toLowerCase();
    var shown = 0;
    cards.forEach(function(c){
      var okG = filter === 'all' ? true
              : filter === 'notrun' ? c.hasAttribute('data-notrun')
              : c.getAttribute('data-g') === filter;
      var okT = !term || c.getAttribute('data-text').indexOf(term) !== -1;
      var on = okG && okT;
      c.hidden = !on;
      if(on) shown++;
      // a hidden card should not stay expanded behind the filter
      if(!on) c.open = false;
    });
    groups.forEach(function(g){
      var vis = g.querySelectorAll('details.cmd:not([hidden])').length;
      g.hidden = vis === 0;
      var c = g.querySelector('.cnt');
      if(c) c.textContent = vis;
    });
    count.textContent = shown + ' of ' + cards.length;
    empty.classList.toggle('on', shown === 0);
  }

  q.addEventListener('input', apply);
  chips.addEventListener('click', function(e){
    var b = e.target.closest('button[data-f]');
    if(!b) return;
    filter = b.getAttribute('data-f');
    [].forEach.call(chips.querySelectorAll('button[data-f]'), function(x){
      x.setAttribute('aria-pressed', String(x === b));
    });
    apply();
  });
  apply();
})();
</script>

</body>
</html>
'''

if __name__ == '__main__':
    main()
