# -*- coding: utf-8 -*-
import sys; sys.path.insert(0,'.')
from build import build

def t(en, cn, zh):
    """英文 + 繁體。中間那個參數保留是為了讓舊的呼叫不用改,但不會輸出 ——
    站上的 assets/lang.js 會在執行時把繁體轉成簡體,中文只維護一份。"""
    return '<span class="en">%s</span><span class="zh">%s</span>' % (en, zh)
def p(en, cn, zh, cls='')  :
    c = ' class="%s"' % cls if cls else ''
    return ('<p%s>' % c) + t(en, cn, zh) + '</p>\n\n'
def h2(en, cn, zh, i=None):
    a = ' id="%s"' % i if i else ''
    return '<h2%s>%s</h2>\n\n' % (a, t(en, cn, zh))
def h3(en, cn, zh):
    return '<h3>%s</h3>\n\n' % t(en, cn, zh)
def table(cols, rows):
    o = '<div class="scroll">\n<table>\n  <thead><tr>'
    for c in cols:
        cls = ' class="n"' if c[0] == 'n' else ''
        o += '<th%s>%s</th>' % (cls, t(*c[1:]))
    o += '</tr></thead>\n  <tbody>\n'
    for r in rows:
        rc = ' class="%s"' % r[0] if r[0] else ''
        o += '    <tr%s>' % rc
        for cell in r[1]:
            if isinstance(cell, tuple):
                o += '<td>%s</td>' % t(*cell)
            else:
                o += '<td class="n">%s</td>' % cell
        o += '</tr>\n'
    return o + '  </tbody>\n</table>\n</div>\n\n'

META = dict(
  title='What the IMX410&rsquo;s binning actually does',
  ogtitle="What the IMX410's pixel binning actually does",
  desc="The SIGMA fp's OG3K and OG2K modes go through the sensor and nothing else, so they show what the IMX410 really does when it is asked to bin. Vertically it combines two rows. Horizontally it combines nothing. The 3x mode throws one row in three away, and none of it buys you light.",
  ogdesc="Measured from frames. Vertically the IMX410 combines two rows; horizontally it interpolates; the 3x mode discards one row in three; and it averages rather than sums.",
  h1=t('What the IMX410&rsquo;s binning actually does',
       'IMX410 的像素合并到底做了什么',
       'IMX410 的像素合併到底做了什麼'),
  lede=p('The menu calls the fp&rsquo;s two video modes 2&times;2 and 3&times;3. Seven '
         'photographs of one scene say that is not what happens. Up and down, the sensor '
         'really does combine rows. Left and right, it combines nothing at all. And the '
         '&divide;3 mode throws one row in three away.',
         '菜单把 fp 的两个录像模式写成 2&times;2 和 3&times;3。同一个场景的七张照片说，'
         '实际不是这样。上下方向，感光元件确实在合并行；左右方向，它根本没有合并任何东西。'
         '而 &divide;3 模式每三行会丢掉一行。',
         '選單把 fp 的兩個錄影模式寫成 2&times;2 和 3&times;3。同一個場景的七張照片說,'
         '實際不是這樣。上下方向,感光元件確實在合併列;左右方向,它根本沒有合併任何東西。'
         '而 &divide;3 模式每三列會丟掉一列。', cls='lede'),
  chips='''    <ul class="chips">
      <li><b>M98</b> <span class="en">&divide;2 &mdash; OG3K</span><span class="zh">&divide;2 &mdash; OG3K</span></li>
      <li><b>M139</b> <span class="en">&divide;3 &mdash; OG2K</span><span class="zh">&divide;3 &mdash; OG2K</span></li>
      <li><b>2&times;2 = 3.2</b> <span class="en">cells, not 4</span><span class="zh">個格子,不是 4</span></li>
    </ul>''',
)

B = ''

B += h2('Why these two modes', '为什么是这两个模式', '為什麼是這兩個模式', 'why')
B += p('The sensor has about 24 million light-collecting cells. A video frame needs two '
       'to eight million, so cells have to be turned into fewer numbers before anything '
       'reaches the card. Most modes do part of that on the sensor and part in a resizing '
       'circuit afterwards. <b>OG3K and OG2K are the only two that go through the sensor '
       'and nothing else</b> &mdash; which makes them the only clean look at what the '
       'IMX410 itself does.',
       '感光元件上大约有 2400 万个收光的小格子。一张视频画面只需要两百到八百万个，'
       '所以在写进卡之前，一定要把很多格子变成比较少的数字。大部分模式是感光元件做一半、'
       '后面的缩图电路做一半。<b>OG3K 和 OG2K 是唯二只经过感光元件、后面什么都没有的模式</b>'
       '—— 所以它们是唯一能干净看到 IMX410 本身在做什么的窗口。',
       '感光元件上大約有 2400 萬個收光的小格子。一張影片畫面只需要兩百到八百萬個,'
       '所以在寫進卡之前,一定要把很多格子變成比較少的數字。大部分模式是感光元件做一半、'
       '後面的縮圖電路做一半。<b>OG3K 和 OG2K 是唯二只經過感光元件、後面什麼都沒有的模式</b>'
       ' —— 所以它們是唯一能乾淨看到 IMX410 本身在做什麼的窗口。')
B += table(
  [('t','mode','模式','模式'), ('t','what it is','是什么','是什麼'),
   ('n','output','输出','輸出'), ('n','rolling shutter','卷帘','捲簾')],
  [('hl',[('<b>M98</b> &mdash; OG3K','<b>M98</b> &mdash; OG3K','<b>M98</b> &mdash; OG3K'),
          ('sensor &divide;2','感光元件 &divide;2','感光元件 &divide;2'),'3024&times;2010','12.44 ms']),
   ('hl',[('<b>M139</b> &mdash; OG2K','<b>M139</b> &mdash; OG2K','<b>M139</b> &mdash; OG2K'),
          ('sensor &divide;3','感光元件 &divide;3','感光元件 &divide;3'),'2016&times;1344','8.31 ms'])])

B += h2('Up and down: it really does combine rows', '上下：它真的在合并行', '上下:它真的在合併列', 'vertical')
B += p('In the &divide;2 mode two rows of the same colour are combined into one, half '
       'and half, exactly as you would hope. Nothing is weighted more than the other, and '
       'nothing is skipped.',
       '在 &divide;2 模式下，两条同色行被合成一条，各占一半，和你期望的完全一样。'
       '没有哪一条权重比较高，也没有跳过任何一条。',
       '在 &divide;2 模式下,兩條同色列被合成一條,各佔一半,和你期望的完全一樣。'
       '沒有哪一條權重比較高,也沒有跳過任何一條。')
B += p('<b>The proof is in the spacing.</b> If rows are genuinely merged in pairs, the '
       'rows that come out are not evenly spaced &mdash; each output row sits at the '
       'middle of its own pair, so the gaps go long, short, long, short. That is measurable '
       'inside a single frame, without any reference image: the two green channels of the '
       'Bayer pattern should sit exactly half a pixel apart, and in OG3K they sit a quarter '
       'apart instead. <b>No resizing circuit produces that.</b> It is what row merging '
       'looks like from the outside.',
       '<b>证据在间距上。</b>如果行真的是成对合并的，出来的行间距就不会均匀 —— '
       '每一条输出行落在自己那一对的中间，所以间隔会长、短、长、短。'
       '这件事在一张画面里就量得出来，不需要参考图：拜耳图案的两个绿色通道本来应该'
       '正好差半个像素，而 OG3K 里它们只差四分之一。<b>任何缩图电路都做不出这个。</b>'
       '这就是行合并从外面看起来的样子。',
       '<b>證據在間距上。</b>如果列真的是成對合併的,出來的列間距就不會均勻 —— '
       '每一條輸出列落在自己那一對的中間,所以間隔會長、短、長、短。'
       '這件事在一張畫面裡就量得出來,不需要參考圖:拜耳圖案的兩個綠色通道本來應該'
       '正好差半個像素,而 OG3K 裡它們只差四分之一。<b>任何縮圖電路都做不出這個。</b>'
       '這就是列合併從外面看起來的樣子。')

B += h2('The &divide;3 mode only combines two rows, and bins the third',
        '&divide;3 模式只合并两行，第三行丢掉',
        '&divide;3 模式只合併兩列,第三列丟掉', 'div3')
B += p('The menu calls M139 a 3&times;3. It is not. Vertically it still combines only '
       '<b>two</b> rows of every three, and the third is simply not used. A third of the '
       'light that landed on the sensor never reaches the file, and the detail that was on '
       'that row is gone.',
       '菜单把 M139 写成 3&times;3。它不是。垂直方向它还是只合并每三行里的<b>两行</b>，'
       '第三行根本没有用到。打在感光元件上的光有三分之一没有进到文件里，'
       '那一行上的细节也就没了。',
       '選單把 M139 寫成 3&times;3。它不是。垂直方向它還是只合併每三列裡的<b>兩列</b>,'
       '第三列根本沒有用到。打在感光元件上的光有三分之一沒有進到檔案裡,'
       '那一列上的細節也就沒了。')
B += p('<b>This is not guesswork from the pixels.</b> The firmware carries a four-number '
       'tag for every mode, and for the eight &divide;3 modes it reads '
       '<code class="k">(3,2,3,3)</code>. The first two numbers are the tap counts per axis, '
       'and that lone <b>2</b> is the vertical one. The pixels and the camera&rsquo;s own '
       'ROM table say the same thing.',
       '<b>这不是从像素上猜的。</b>固件为每个模式带了一组四个数字的标签，'
       '八个 &divide;3 模式上写的是 <code class="k">(3,2,3,3)</code>。'
       '前两个数字是每个方向的抽头数，那个孤零零的 <b>2</b> 就是垂直方向。'
       '像素和相机自己的 ROM 表说的是同一件事。',
       '<b>這不是從像素上猜的。</b>韌體為每個模式帶了一組四個數字的標籤,'
       '八個 &divide;3 模式上寫的是 <code class="k">(3,2,3,3)</code>。'
       '前兩個數字是每個方向的抽頭數,那個孤零零的 <b>2</b> 就是垂直方向。'
       '像素和相機自己的 ROM 表說的是同一件事。')

B += h2('Left and right: nothing is combined &mdash; it is calculated',
        '左右：根本没有合并 —— 是算出来的',
        '左右:根本沒有合併 —— 是算出來的', 'horizontal')
B += p('Sideways, no cells are merged. The camera picks a position <em>between</em> two '
       'neighbouring cells and works out how bright it would probably be, by mixing the two '
       'in some proportion &mdash; like mixing two paints to get a shade in between. '
       'Nothing is collected twice. A new number is invented from the numbers next door.',
       '横的方向，没有任何格子被合并。相机挑一个落在<em>两个相邻格子中间</em>的位置，'
       '再按比例把那两格混起来，算出它「大概应该多亮」—— 就像把两种颜料调出中间色。'
       '没有东西被多收一次，只是从旁边的数字生出一个新数字。',
       '橫的方向,沒有任何格子被合併。相機挑一個落在<em>兩個相鄰格子中間</em>的位置,'
       '再按比例把那兩格混起來,算出它「大概應該多亮」—— 就像把兩種顏料調出中間色。'
       '沒有東西被多收一次,只是從旁邊的數字生出一個新數字。')
B += p('The giveaway is that the mixing proportions are <b>unequal, and they flip</b> '
       'between even and odd output columns &mdash; roughly 27:73, then 73:27. Combining '
       'charge cannot do that. Resampling onto an evenly spaced grid does exactly that.',
       '看出来的地方在于混合的比例是<b>不相等的，而且在偶数列和奇数列之间对调</b>'
       '—— 大约 27:73，然后 73:27。电荷合并做不出这件事，'
       '而「重新取样到一个均匀的网格上」正好就会这样。',
       '看出來的地方在於混合的比例是<b>不相等的,而且在偶數行和奇數行之間對調</b>'
       ' —— 大約 27:73,然後 73:27。電荷合併做不出這件事,'
       '而「重新取樣到一個均勻的網格上」正好就會這樣。')
B += table(
  [('t','','',''), ('t','up and down','上下','上下'), ('t','left and right','左右','左右')],
  [('hl',[('<b>OG3K</b> &divide;2','<b>OG3K</b> &divide;2','<b>OG3K</b> &divide;2'),
          ('<b>really combines</b> 2 rows, 50/50','<b>真的合并</b> 2 行，各一半','<b>真的合併</b> 2 列,各一半'),
          ('2-tap mix, 27:73','2 点混合，27:73','2 點混合,27:73')]),
   ('hl',[('<b>OG2K</b> &divide;3','<b>OG2K</b> &divide;3','<b>OG2K</b> &divide;3'),
          ('combines 2 rows, <b>discards the 3rd</b>','合并 2 行，<b>第三行丢掉</b>','合併 2 列,<b>第三列丟掉</b>'),
          ('3-tap mix, 25:50:25','3 点混合，25:50:25','3 點混合,25:50:25')])])

B += h2('It averages, it does not sum &mdash; so you get no free stop',
        '它是平均，不是相加 —— 所以没有白送的一级',
        '它是平均,不是相加 —— 所以沒有白送的一級', 'average')
B += p('People expect binning to gather light: merge four cells and the one you keep has '
       'four cells&rsquo; worth. That is not what comes out. Whatever gets combined is '
       'divided back down afterwards.',
       '一般人期望合并会收光：四格并成一格，留下的那格就有四格份的光。'
       '出来的结果不是这样。不管合并了什么，后面都会除回去。',
       '一般人期望合併會收光:四格併成一格,留下的那格就有四格份的光。'
       '出來的結果不是這樣。不管合併了什麼,後面都會除回去。')
B += p('<b>How you can tell:</b> &divide;3 is not brighter than &divide;2. At the same ISO '
       'and shutter the two sit at the same level &mdash; 127.1 against 124.8. If charge '
       'were really being added up, &divide;3 would be more than twice as bright. Every '
       'video mode also sits <b>1.32&nbsp;EV below</b> the 6K still at identical settings, '
       'and the DNG files say so themselves in their exposure tag.',
       '<b>怎么看出来的：</b>&divide;3 并没有比 &divide;2 亮。同样的 ISO 和快门下，'
       '两者亮度一样 —— 127.1 对 124.8。如果电荷真的被加起来，&divide;3 应该要亮两倍以上。'
       '而且在完全相同的设定下，每个视频模式都比 6K 静态<b>暗 1.32&nbsp;EV</b>，'
       'DNG 文件自己的曝光标签也是这么写的。',
       '<b>怎麼看出來的:</b>&divide;3 並沒有比 &divide;2 亮。同樣的 ISO 和快門下,'
       '兩者亮度一樣 —— 127.1 對 124.8。如果電荷真的被加起來,&divide;3 應該要亮兩倍以上。'
       '而且在完全相同的設定下,每個影片模式都比 6K 靜態<b>暗 1.32&nbsp;EV</b>,'
       'DNG 檔自己的曝光標籤也是這麼寫的。')
B += p('<b>What this test cannot tell you</b> is whether the dividing happens before or '
       'after the read. &ldquo;Add the charge, then halve it&rdquo; and &ldquo;read both '
       'rows, then average&rdquo; give the same brightness and the same noise in daylight, '
       'and differ only in the dark. That one is still open.',
       '<b>但这个测试分不出来的是</b>除法发生在读出之前还是之后。'
       '「电荷相加再除以二」和「两行都读出来再平均」在白天会给出一样的亮度和一样的噪点，'
       '只在暗部才不同。这一点还没解。',
       '<b>但這個測試分不出來的是</b>除法發生在讀出之前還是之後。'
       '「電荷相加再除以二」和「兩列都讀出來再平均」在白天會給出一樣的亮度和一樣的雜訊,'
       '只在暗部才不同。這一點還沒解。', cls='note')

B += h2('What it costs', '代价是什么', '代價是什麼', 'cost')
B += p('Because the mixing weights are uneven, an output pixel does not average as many '
       'cells as the name suggests. Count them properly and a &ldquo;2&times;2&rdquo; '
       'averages <b>3.2</b> cells, not 4. A &ldquo;3&times;3&rdquo; averages '
       '<b>5.33</b>, not 9 &mdash; that is the discarded row showing up as a number.',
       '因为混合的权重不均匀，一个输出像素平均到的格子数并没有名字说的那么多。'
       '认真数的话，「2&times;2」平均了 <b>3.2</b> 个格子，不是 4；'
       '「3&times;3」平均了 <b>5.33</b> 个，不是 9 —— 被丢掉的那一行就体现在这个数字上。',
       '因為混合的權重不均勻,一個輸出像素平均到的格子數並沒有名字說的那麼多。'
       '認真數的話,「2&times;2」平均了 <b>3.2</b> 個格子,不是 4;'
       '「3&times;3」平均了 <b>5.33</b> 個,不是 9 —— 被丟掉的那一列就體現在這個數字上。')
B += table(
  [('t','mode','模式','模式'), ('n','on the label','名义上','名義上'),
   ('n','actually','实际','實際'), ('n','noise benefit','降噪','降噪')],
  [('hl',[('<b>OG3K</b> &divide;2','<b>OG3K</b> &divide;2','<b>OG3K</b> &divide;2'),'4','<b>3.2</b>','&minus;0.85 EV']),
   ('hl',[('<b>OG2K</b> &divide;3','<b>OG2K</b> &divide;3','<b>OG2K</b> &divide;3'),'9','<b>5.33</b>','&minus;1.21 EV']),
   ('ref',[('<i>a perfect 3&times;3</i>','<i>完美的 3&times;3</i>','<i>完美的 3&times;3</i>'),'<i>9</i>','<i>9</i>','<i>&minus;1.58 EV</i>'])])
B += p('The noise side is the good news and it is small. The real cost is elsewhere: a '
       'reduction that skips rows cannot represent fine repeating detail, and what it '
       'cannot represent does not vanish politely &mdash; it comes back as a coarser '
       'pattern that was never in front of the lens. On a dense fabric weave, '
       '<b>&divide;3 goes wrong about six times as often as &divide;2</b>.',
       '噪点这一侧是好消息，而且差距不大。真正的代价在别处：'
       '一个会跳行的缩减方式没办法表现细密的重复花纹，而它表现不了的东西不会乖乖消失 —— '
       '会变成一个镜头前根本没有的、比较粗的图案回到画面上。在密织的布料上，'
       '<b>&divide;3 出错的程度大约是 &divide;2 的六倍</b>。',
       '雜訊這一側是好消息,而且差距不大。真正的代價在別處:'
       '一個會跳列的縮減方式沒辦法表現細密的重複花紋,而它表現不了的東西不會乖乖消失 —— '
       '會變成一個鏡頭前根本沒有的、比較粗的圖案回到畫面上。在密織的布料上,'
       '<b>&divide;3 出錯的程度大約是 &divide;2 的六倍</b>。')
B += table(
  [('t','','',''), ('n','dense weave','密织布料','密織布料'),
   ('n','everyday material','一般素材','一般素材'), ('n','vs a perfect box','对完美盒平均','對完美盒平均')],
  [('hl',[('<b>OG3K</b> &divide;2','<b>OG3K</b> &divide;2','<b>OG3K</b> &divide;2'),'<b>3.9%</b>','<b>0.7%</b>',
          ('nearly there &mdash; 3.0% / 0.5%','已经很接近 —— 3.0% / 0.5%','已經很接近 —— 3.0% / 0.5%')]),
   ('bad',[('<b>OG2K</b> &divide;3','<b>OG2K</b> &divide;3','<b>OG2K</b> &divide;3'),'<b>22.7%</b>','2.7%',
          ('<b>3.6&times; worse</b> &mdash; 6.2% / 0.6%','<b>差 3.6 倍</b> —— 6.2% / 0.6%','<b>差 3.6 倍</b> —— 6.2% / 0.6%')])])
B += p('Lower is better; the numbers are how much of the picture came out as something '
       'that was not there. <b>&divide;2 is close to the best a two-row merge could '
       'possibly do. &divide;3 is nowhere near</b>, and the gap is the thrown-away row.',
       '数字越小越好，它代表画面里有多少东西变成了原本不存在的样子。'
       '<b>&divide;2 已经接近「两行合并」能做到的极限；&divide;3 差得远</b>，'
       '差的那一段就是被丢掉的那一行。',
       '數字越小越好,它代表畫面裡有多少東西變成了原本不存在的樣子。'
       '<b>&divide;2 已經接近「兩列合併」能做到的極限;&divide;3 差得遠</b>,'
       '差的那一段就是被丟掉的那一列。')

B += h2('Which mode to actually use', '实际该用哪个模式', '實際該用哪個模式', 'use')
B += table(
  [('t','you want','你要的是','你要的是'), ('t','take','选','選'),
   ('n','rolling shutter','卷帘','捲簾'), ('t','why','理由','理由')],
  [('hl',[('<b>3K, best picture</b>','<b>3K，画质优先</b>','<b>3K,畫質優先</b>'),'<b>M98</b>','12.44 ms',
          ('the cleanest thing this camera makes','这台相机做得出来最干净的','這台相機做得出來最乾淨的')]),
   ('',[('3K, less rolling shutter','3K，卷帘要小','3K,捲簾要小'),'M117','9.22 ms',
        ('same picture, but <b>1.33&times; noisier</b>','画面一样，但<b>吵 1.33 倍</b>','畫面一樣,但<b>吵 1.33 倍</b>')]),
   ('hl',[('<b>2K, default</b>','<b>2K，预设</b>','<b>2K,預設</b>'),'<b>M139</b>','8.31 ms',
          ('fine on ordinary subjects, best rolling shutter','一般题材没问题，卷帘全场最好','一般題材沒問題,捲簾全場最好')]),
   ('',[('2K, high speed','2K，高速','2K,高速'),'M56','<b>6.16 ms</b>',
        ('up to 119 fps','最高 119 fps','最高 119 fps')])])
B += p('<b>M117 is not the quiet one.</b> It used to be written up that way here, from two '
       'folders whose names had been swapped. Measured properly it reads 1.205 against '
       'M98&rsquo;s 0.904 &mdash; it buys 26% off the rolling shutter and nothing else. '
       'When a measurement contradicts the person who was there, check the labels before '
       'trusting the measurement.',
       '<b>M117 不是比较安静的那个。</b>这里以前是那样写的，'
       '来源是两个名字被对调的文件夹。正确量出来是 1.205 对 M98 的 0.904 —— '
       '它换到的只有 26% 的卷帘改善，没有别的。'
       '当量测和在场的人矛盾时，先检查标签，再相信量测。',
       '<b>M117 不是比較安靜的那個。</b>這裡以前是那樣寫的,'
       '來源是兩個名字被對調的資料夾。正確量出來是 1.205 對 M98 的 0.904 —— '
       '它換到的只有 26% 的捲簾改善,沒有別的。'
       '當量測和在場的人矛盾時,先檢查標籤,再相信量測。', cls='note')

B += h2('If you are developing the RAW', '如果你要自己解 RAW', '如果你要自己解 RAW', 'demosaic')
B += p('<b>OG3K&rsquo;s rows are not evenly spaced</b>, for the reason in the second '
       'section. Most demosaic code assumes they are, and on a diagonal edge that shows up '
       'as a faint stair-step. Resampling the frame to an even row grid first, before '
       'demosaicing, removes it.',
       '<b>OG3K 的行间距不是均匀的</b>，原因在第二节。'
       '大部分去马赛克的程序都假设它是均匀的，结果在斜边上会出现淡淡的阶梯。'
       '先把画面重新取样到均匀的行间距，再去马赛克，就不会有。',
       '<b>OG3K 的列間距不是均勻的</b>,原因在第二節。'
       '大部分去馬賽克的程式都假設它是均勻的,結果在斜邊上會出現淡淡的階梯。'
       '先把畫面重新取樣到均勻的列間距,再去馬賽克,就不會有。')
B += p('<b>On OG2K, a chroma median pass helps more than changing algorithm.</b> Its false '
       'colour comes from the discarded row, not from the demosaic, so a better demosaic '
       'cannot fix it &mdash; but cleaning up the colour after the fact can.',
       '<b>OG2K 上，色度中值滤波比换算法有用。</b>它的伪色来自被丢掉的那一行，'
       '不是来自去马赛克，所以换更好的算法救不了 —— 但事后把颜色清一清可以。',
       '<b>OG2K 上,色度中值濾波比換演算法有用。</b>它的偽色來自被丟掉的那一列,'
       '不是來自去馬賽克,所以換更好的演算法救不了 —— 但事後把顏色清一清可以。')

B += h2('Where this comes from', '这些是怎么来的', '這些是怎麼來的', 'sources')
B += p('Every number on this page is fitted from <b>seven stills shot and released by '
       'Jose</b>: one frame per mode of the same scene, ISO&nbsp;400, 1/25&nbsp;s, f/3.5, '
       '25p, Ver.5.02 with fpSup, camera serial zeroed and the image data left '
       'byte-identical. Nothing else went into the kernels.',
       '这一页上每一个数字，都是从 <b>Jose 拍摄并公开的七张静态照片</b>拟合出来的：'
       '一个模式一张，同场景，ISO&nbsp;400、1/25&nbsp;秒、f/3.5、25p，Ver.5.02 搭 fpSup，'
       '相机序号归零、图像数据保持逐位相同。核里没有放进别的东西。',
       '這一頁上每一個數字,都是從 <b>Jose 拍攝並公開的七張靜態照片</b>擬合出來的:'
       '一個模式一張,同場景,ISO&nbsp;400、1/25&nbsp;秒、f/3.5、25p,Ver.5.02 搭 fpSup,'
       '相機序號歸零、影像資料保持逐位元相同。核裡沒有放進別的東西。')
B += p('Three separate methods had to agree before anything here was written down: fitting '
       'the weights directly, checking them against how noise grows with brightness, and '
       'measuring the row spacing inside a single frame. Where they disagreed, the page '
       'says so.',
       '这里每写下一件事之前，三种独立的量法都必须对上：直接拟合权重、'
       '用「噪点如何随亮度增长」交叉检查、以及在单张画面里量行间距。'
       '有对不上的地方，页面上都写了。',
       '這裡每寫下一件事之前,三種獨立的量法都必須對上:直接擬合權重、'
       '用「雜訊如何隨亮度增長」交叉檢查、以及在單張畫面裡量列間距。'
       '有對不上的地方,頁面上都寫了。')
B += p('<b>Still open:</b> whether the dividing happens before or after the read, and '
       'whether a true three-row merge is configurable at all &mdash; nothing in the '
       'decoded register set separates two rows from three, so it may simply not be.',
       '<b>还没解：</b>除法发生在读出之前还是之后，'
       '以及真正的三行合并到底能不能设定 —— 已解码的寄存器里没有任何一个把两行和三行分开，'
       '所以有可能它根本不可设定。',
       '<b>還沒解:</b>除法發生在讀出之前還是之後,'
       '以及真正的三列合併到底能不能設定 —— 已解碼的暫存器裡沒有任何一個把兩列和三列分開,'
       '所以有可能它根本不可設定。', cls='note')
B += p('The stage that comes <em>after</em> the sensor &mdash; the resizing circuit every '
       'other mode goes through &mdash; is a separate page: '
       '<a href="rwzm-resampler.html">What the RWZM resizer does</a>. '
       'The full technical version of both, with every table, is '
       '<a href="reduction-kernels.html">here</a>.',
       '感光元件<em>后面</em>那一关 —— 其他模式都会经过的缩图电路 —— 在另一页：'
       '<a href="rwzm-resampler.html">RWZM 缩图电路做了什么</a>。'
       '两者的完整技术版、所有表格，在<a href="reduction-kernels.html">这里</a>。',
       '感光元件<em>後面</em>那一關 —— 其他模式都會經過的縮圖電路 —— 在另一頁:'
       '<a href="rwzm-resampler.html">RWZM 縮圖電路做了什麼</a>。'
       '兩者的完整技術版、所有表格,在<a href="reduction-kernels.html">這裡</a>。')

if __name__ == '__main__':
    print('built', build('imx410-binning.html', META, B), 'bytes')
