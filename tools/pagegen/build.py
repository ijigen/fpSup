import io, os
STYLE = io.open('style3.css', encoding='utf-8').read()
import os
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'explainers') + os.sep

HEAD = '''<!doctype html>
<html lang="en" data-lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} &mdash; fpSup</title>
<meta name="description" content="{desc}">

<meta property="og:type" content="article">
<meta property="og:url" content="https://ijigen.github.io/fpSup/explainers/{slug}">
<meta property="og:title" content="{ogtitle}">
<meta property="og:description" content="{ogdesc}">
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
''' + STYLE + '''</style>
</head>
<body>

<div class="topbar">
  <a class="back" href="../research.html"><span class="en">&larr; Firmware research</span><span class="zh">&larr; 韌體研究</span></a>
  <div class="lang" role="group" aria-label="Language / 語言 / 语言">
    <button type="button" data-set="en" aria-pressed="true">EN</button>
    <button type="button" data-set="cn" aria-pressed="false">中</button>
    <button type="button" data-set="zh" aria-pressed="false">繁</button>
  </div>
</div>

<header class="hero">
  <div class="hero-text">
    <h1>{h1}</h1>
{lede}
{chips}
  </div>
</header>

'''

FOOT = '''
<footer>
  <p><a href="../">fpSup</a> &middot;
  <a href="../research.html"><span class="en">Firmware research</span><span class="zh">韌體研究</span></a> &middot;
  <a href="https://discord.gg/XeFK5zNZpT">Discord</a> &middot;
  <a href="https://www.youtube.com/@fp-sup">YouTube</a> &middot;
  <a href="https://github.com/ijigen/fpSup"><span class="en">Repository</span><span class="zh">程式庫</span></a></p>
</footer>

<script src="../assets/lang.js?v=0183bc5d" defer></script>

</body>
</html>
'''


def build(slug, meta, body):
    head = HEAD
    for k, v in dict(meta, slug=slug).items():
        head = head.replace('{%s}' % k, v)
    html = head + body + FOOT
    io.open(OUT + slug, 'w', encoding='utf-8').write(html)
    return len(html)
