# -*- coding: utf-8 -*-
import sys; sys.path.insert(0,'.')
from build import build
from p1 import t, p, h2, h3, table   # reuse helpers

META = dict(
  title='What the RWZM resizer does',
  ogtitle='What the SIGMA fp&rsquo;s RWZM resizer does',
  desc="Every fp video mode except OG3K and OG2K passes through a resizing circuit called RWZM. It shrinks without smoothing first, and it uses sixteen slightly different recipes in rotation. That is where FHD's softness, its aliasing and its horizontal banding all come from - and a ratio whose denominator is small avoids the banding entirely.",
  ogdesc='It shrinks without smoothing first, and rotates through sixteen recipes. That is where FHD goes wrong, and picking a ratio with a small denominator avoids it.',
  h1=t('What the RWZM resizer does',
       'RWZM 缩图电路做了什么',
       'RWZM 縮圖電路做了什麼'),
  lede=p('After the sensor there is a second machine that shrinks the picture the rest of '
         'the way. Every mode except OG3K and OG2K goes through it. It turns out to matter '
         'more than the binning does &mdash; because it shrinks without smoothing first, '
         'and because it does not treat every row the same way.',
         '感光元件后面还有第二台机器，负责把画面缩到剩下的尺寸。'
         '除了 OG3K 和 OG2K 以外，所有模式都会经过它。'
         '它的影响其实比像素合并还大 —— 因为它缩图之前不先做平滑，'
         '而且它不是每一行都用同样的方式处理。',
         '感光元件後面還有第二台機器,負責把畫面縮到剩下的尺寸。'
         '除了 OG3K 和 OG2K 以外,所有模式都會經過它。'
         '它的影響其實比像素合併還大 —— 因為它縮圖之前不先做平滑,'
         '而且它不是每一列都用同樣的方式處理。', cls='lede'),
  chips='''    <ul class="chips">
      <li><b>16</b> <span class="en">recipes, in rotation</span><span class="zh">套做法,輪流用</span></li>
      <li><b>0</b> <span class="en">smoothing before it shrinks</span><span class="zh">縮圖前的平滑</span></li>
      <li><b>FHD</b> <span class="en">is the worst case</span><span class="zh">是最糟的情況</span></li>
    </ul>''',
)

B = ''

B += h2('Where this stage sits', '这一关在哪里', '這一關在哪裡', 'where')
B += p('The sensor cannot produce the final frame size on its own. Whatever it hands over, '
       'a separate circuit &mdash; the firmware calls it <b>RWZM</b> &mdash; shrinks the '
       'rest of the way.',
       '感光元件自己做不出最终的画面尺寸。不管它交出什么，'
       '都有一个独立的电路 —— 固件里叫 <b>RWZM</b> —— 把剩下的尺寸缩完。',
       '感光元件自己做不出最終的畫面尺寸。不管它交出什麼,'
       '都有一個獨立的電路 —— 韌體裡叫 <b>RWZM</b> —— 把剩下的尺寸縮完。')
B += table(
  [('t','mode','模式','模式'), ('t','sensor stage','感光元件那一关','感光元件那一關'),
   ('t','then RWZM','然后 RWZM','然後 RWZM')],
  [('hl',[('<b>OG3K</b>','<b>OG3K</b>','<b>OG3K</b>'),('&divide;2','&divide;2','&divide;2'),
          ('<b>none</b> &mdash; straight to the card','<b>没有</b> —— 直接写卡','<b>沒有</b> —— 直接寫卡')]),
   ('hl',[('<b>OG2K</b>','<b>OG2K</b>','<b>OG2K</b>'),('&divide;3','&divide;3','&divide;3'),
          ('<b>none</b>','<b>没有</b>','<b>沒有</b>')]),
   ('',[('UHD','UHD','UHD'),('none','没有','沒有'),('shrinks by 25/16','缩 25/16','縮 25/16')]),
   ('bad',[('<b>FHD</b>','<b>FHD</b>','<b>FHD</b>'),('&divide;2','&divide;2','&divide;2'),
           ('<b>then shrinks by 25/16 again</b>','<b>再缩 25/16</b>','<b>再縮 25/16</b>')])])
B += p('So FHD goes through both stages, UHD goes through this one alone, and the two open '
       'gate modes never touch it. <b>That is the split that decides most of the picture '
       'quality on this camera.</b>',
       '所以 FHD 两关都走，UHD 只走这一关，而两个 open gate 模式完全不碰它。'
       '<b>这台相机大部分的画质差异，就是这条界线决定的。</b>',
       '所以 FHD 兩關都走,UHD 只走這一關,而兩個 open gate 模式完全不碰它。'
       '<b>這台相機大部分的畫質差異,就是這條界線決定的。</b>')

B += h2('Problem one: it shrinks without smoothing first',
        '问题一：它缩图之前不先平滑',
        '問題一:它縮圖之前不先平滑', 'nofilter')
B += p('When you make a picture smaller you are throwing away sample points. Anything finer '
       'than the new spacing cannot be recorded &mdash; but it does not politely disappear. '
       'It comes back as a <em>different, coarser</em> pattern that was never in front of '
       'the lens: a fabric weave turns into wide stripes, a brick wall into wavy bands, a '
       'fine grid grows colour fringes.',
       '把一张图缩小，等于在丢掉取样点。比新间距还细的东西是记录不下来的 —— '
       '但它不会乖乖消失。它会变成一个<em>完全不同、比较粗的</em>图案回到画面上，'
       '而那个图案根本不在镜头前：布料的织纹变成宽条纹、砖墙变成波浪、细格子长出彩色的边。',
       '把一張圖縮小,等於在丟掉取樣點。比新間距還細的東西是記錄不下來的 —— '
       '但它不會乖乖消失。它會變成一個<em>完全不同、比較粗的</em>圖案回到畫面上,'
       '而那個圖案根本不在鏡頭前:布料的織紋變成寬條紋、磚牆變成波浪、細格子長出彩色的邊。')
B += p('The standard cure is to blur the picture slightly <em>before</em> shrinking, so the '
       'too-fine detail is gone before it can misbehave. <b>This circuit does not do that.</b> '
       'Every one of its sixteen recipes is a narrow two-point mix, and the width never '
       'changes no matter how much you are shrinking by.',
       '标准的解法是在缩之前<em>先</em>把画面稍微模糊一点，'
       '让太细的细节在捣乱之前就先消失。<b>这个电路没有做这件事。</b>'
       '它十六套做法每一套都只是很窄的两点混合，而且不管你要缩多少，宽度都不变。',
       '標準的解法是在縮之前<em>先</em>把畫面稍微模糊一點,'
       '讓太細的細節在搗亂之前就先消失。<b>這個電路沒有做這件事。</b>'
       '它十六套做法每一套都只是很窄的兩點混合,而且不管你要縮多少,寬度都不變。')
B += p('<b>The consequence is one sentence:</b> whatever protection a mode has against '
       'false patterns, it gets entirely from the sensor stage. A mode that skips the '
       'sensor stage gets none.',
       '<b>结论只有一句：</b>一个模式对假花纹的抵抗力，全部来自感光元件那一关。'
       '跳过那一关的模式，一点都没有。',
       '<b>結論只有一句:</b>一個模式對假花紋的抵抗力,全部來自感光元件那一關。'
       '跳過那一關的模式,一點都沒有。', cls='note')

B += h2('Problem two: it does not treat every row the same',
        '问题二：它不是每一行都一样处理',
        '問題二:它不是每一列都一樣處理', 'phases')
B += p('To land on sample positions that fall between the input pixels, the circuit keeps '
       '<b>sixteen slightly different recipes</b> and rotates through them. Row 1, row 2 '
       'and row 3 each get handled a little differently, and the cycle comes back around '
       'every sixteenth row.',
       '为了取到落在输入像素之间的位置，这个电路准备了<b>十六套略有不同的做法</b>，'
       '轮流使用。第 1 行、第 2 行、第 3 行各自被处理得有一点点不一样，'
       '而这个循环每十六行回来一次。',
       '為了取到落在輸入像素之間的位置,這個電路準備了<b>十六套略有不同的做法</b>,'
       '輪流使用。第 1 列、第 2 列、第 3 列各自被處理得有一點點不一樣,'
       '而這個循環每十六列回來一次。')
B += p('On most subjects nobody would notice. On fine detail the recipes disagree enough '
       'that the sixteen-row cycle prints itself onto the picture &mdash; and because every '
       'pixel in a row shares a recipe, it prints as <b>horizontal banding</b>. That is the '
       '&ldquo;digital look&rdquo; people report in FHD.',
       '一般题材根本不会有人发现。但在细致的细节上，这十六套的差异大到会把那个十六行的'
       '循环印在画面上 —— 而且因为同一行里每个像素共用同一套做法，'
       '印出来就是<b>横向的条带</b>。那就是大家说 FHD「有数位感」的东西。',
       '一般題材根本不會有人發現。但在細緻的細節上,這十六套的差異大到會把那個十六列的'
       '循環印在畫面上 —— 而且因為同一列裡每個像素共用同一套做法,'
       '印出來就是<b>橫向的條帶</b>。那就是大家說 FHD「有數位感」的東西。')
B += h3('The rule worth remembering', '值得记住的那条规则', '值得記住的那條規則')
B += p('How many of the sixteen a mode actually uses depends on the <b>shrink ratio</b> '
       '&mdash; specifically, on the bottom number when you write it as a fraction. FHD '
       'shrinks by 25/16, and 16 on the bottom means all sixteen recipes are in play. '
       'Shrink by 3/2 and only two are ever used. Shrink by a whole number and only one is.',
       '一个模式实际会用到几套，取决于<b>缩图比例</b> —— 更精确地说，'
       '取决于把它写成分数时下面那个数字。FHD 缩的是 25/16，分母 16 代表十六套全开。'
       '缩 3/2 的话只会用到两套；缩整数倍的话只会用到一套。',
       '一個模式實際會用到幾套,取決於<b>縮圖比例</b> —— 更精確地說,'
       '取決於把它寫成分數時下面那個數字。FHD 縮的是 25/16,分母 16 代表十六套全開。'
       '縮 3/2 的話只會用到兩套;縮整數倍的話只會用到一套。')
B += table(
  [('t','shrink by','缩图比例','縮圖比例'), ('n','recipes used','用到几套','用到幾套'),
   ('n','repeats every','重复周期','重複週期'), ('t','banding?','会不会起条带','會不會起條帶')],
  [('bad',[('<b>25/16</b> &mdash; FHD, UHD','<b>25/16</b> —— FHD、UHD','<b>25/16</b> —— FHD、UHD'),
           '<b>16</b>',('16 rows','16 行','16 列'),('<b>yes</b>','<b>会</b>','<b>會</b>')]),
   ('',[('8/5','8/5','8/5'),'5',('5 rows','5 行','5 列'),('barely','几乎不会','幾乎不會')]),
   ('hl',[('<b>3/2</b>','<b>3/2</b>','<b>3/2</b>'),'<b>2</b>',('2 rows','2 行','2 列'),
          ('<b>no</b> &mdash; reads as grain','<b>不会</b> —— 看起来像颗粒','<b>不會</b> —— 看起來像顆粒')]),
   ('hl',[('<b>2, 3</b> &mdash; whole numbers','<b>2、3</b> —— 整数','<b>2、3</b> —— 整數'),'<b>1</b>',
          ('&mdash;','&mdash;','&mdash;'),('<b>no</b>','<b>不会</b>','<b>不會</b>')])])
B += p('Two recipes carry almost as much error as sixteen do &mdash; 17% against 21% of '
       'picture contrast. The difference is that with two, the error flips sign on '
       'alternating rows, so it lands at the finest scale the picture has and reads as '
       'grain. With sixteen it repeats slowly enough to be seen as bands. <b>The problem was '
       'never how much error. It was what shape the error came in.</b>',
       '两套做法带的误差几乎和十六套一样多 —— 占画面对比的 17% 对 21%。'
       '差别在于两套的时候，误差在相邻行之间正负交替，落在画面最细的尺度上，看起来是颗粒；'
       '十六套的时候，它重复得够慢，看起来就是条带。'
       '<b>问题从来不是误差有多少，是误差排成什么形状。</b>',
       '兩套做法帶的誤差幾乎和十六套一樣多 —— 佔畫面對比的 17% 對 21%。'
       '差別在於兩套的時候,誤差在相鄰列之間正負交替,落在畫面最細的尺度上,看起來是顆粒;'
       '十六套的時候,它重複得夠慢,看起來就是條帶。'
       '<b>問題從來不是誤差有多少,是誤差排成什麼形狀。</b>')

B += h2('How bad, in numbers', '到底有多糟，用数字讲', '到底有多糟,用數字講', 'ranking')
B += p('Same reference frames, five different materials, every route the camera can take or '
       'could be made to take. Lower is better: the number is how much of the picture came '
       'out as something that was not there. Italic rows are not real routes &mdash; they '
       'are what a mathematically perfect shrink would score.',
       '同一组参考画面、五种不同材质、相机做得到或可能做得到的每一条路线。'
       '数字越小越好：它代表画面里有多少东西变成了原本不存在的样子。'
       '斜体行不是真的路线，是数学上完美的缩图会拿到的分数。',
       '同一組參考畫面、五種不同材質、相機做得到或可能做得到的每一條路線。'
       '數字越小越好:它代表畫面裡有多少東西變成了原本不存在的樣子。'
       '斜體列不是真的路線,是數學上完美的縮圖會拿到的分數。')
B += table(
  [('t','route','路线','路線'), ('n','dense weave','密织布料','密織布料'),
   ('n','everyday material','一般素材','一般素材'), ('n','noise','噪点','雜訊'),
   ('n','recipes','用几套','用幾套')],
  [('hl',[('<b>OG3K</b> &mdash; sensor only','<b>OG3K</b> —— 只走感光元件','<b>OG3K</b> —— 只走感光元件'),
          '<b>3.9%</b>','<b>0.7%</b>','&times;0.55','&mdash;']),
   ('ref',[('<i>a perfect 2&times;2</i>','<i>完美的 2&times;2</i>','<i>完美的 2&times;2</i>'),
           '<i>3.0%</i>','<i>0.5%</i>','<i>&times;0.50</i>','<i>&mdash;</i>']),
   ('hl',[('<b>OG2K</b> &mdash; sensor only','<b>OG2K</b> —— 只走感光元件','<b>OG2K</b> —— 只走感光元件'),
          '22.7%','<b>2.7%</b>','&times;0.43','&mdash;']),
   ('',[('OG4K &mdash; full read, shrink 3/2','OG4K —— 读满再缩 3/2','OG4K —— 讀滿再縮 3/2'),
        '4.9%','5.1%','&times;0.57','2']),
   ('',[('UHD &mdash; full read, shrink 25/16','UHD —— 读满再缩 25/16','UHD —— 讀滿再縮 25/16'),
        '7.1%','4.8%','&times;0.56','<b>16</b>']),
   ('bad',[('<b>FHD</b> &mdash; &divide;2, then 25/16','<b>FHD</b> —— &divide;2 再縮 25/16','<b>FHD</b> —— &divide;2 再縮 25/16'),
           '13.8%','<b>6.2%</b>','&times;0.31','<b>16</b>']),
   ('bad',[('2K &mdash; full read, shrink 3','2K —— 读满再缩 3 倍','2K —— 讀滿再縮 3 倍'),
           '<b>34.1%</b>','4.7%','&times;0.61','1'])])
B += p('<b>The everyday column splits the table in two, and not where the output size '
       'does.</b> The two routes that never touch the resizer score 0.7% and 2.7%. Every '
       'route that touches it pays between 2.2% and 7.3%, whatever ratio it uses. A sensor '
       'merge applies the same recipe everywhere, so its mistakes are uniform and a little '
       'sharpening takes them back. The resizer uses a different recipe at every position, '
       'so its mistakes change from pixel to pixel &mdash; and that part is gone for good.',
       '<b>「一般素材」那一栏把表切成两半，而切的地方不是输出尺寸。</b>'
       '完全不碰缩图电路的两条是 0.7% 和 2.7%；碰到它的每一条都要付 2.2% 到 7.3%，'
       '不管用什么比例。感光元件的合并在每个位置用同一套做法，所以它犯的错是均匀的，'
       '稍微锐化就能拿回来。缩图电路在每个位置用不同的做法，'
       '所以它犯的错逐像素改变 —— 那一部分救不回来。',
       '<b>「一般素材」那一欄把表切成兩半,而切的地方不是輸出尺寸。</b>'
       '完全不碰縮圖電路的兩條是 0.7% 和 2.7%;碰到它的每一條都要付 2.2% 到 7.3%,'
       '不管用什麼比例。感光元件的合併在每個位置用同一套做法,所以它犯的錯是均勻的,'
       '稍微銳化就能拿回來。縮圖電路在每個位置用不同的做法,'
       '所以它犯的錯逐像素改變 —— 那一部分救不回來。')

B += '''<figure class="dia">
  <video src="assets/reduction/cloth-ab.mp4" controls muted loop playsinline preload="none" aria-label="Six seconds of an A/B comparison on white shirt fabric, three seconds of FHD then three of OG2K."></video>
  <figcaption>
''' + t(
 '<b>Six seconds, cut on the switch.</b> Three of FHD, then three of OG2K, cropped to the '
 'white shirt so you can see the weave; the labels were burned in by the person who shot '
 'it. Under OG2K the weave is a fine, even crosshatch, which is what the cloth is. Under '
 'FHD it goes coarse and blotchy, and the pattern that appears is not the one in front of '
 'the lens.',
 '<b>六秒，正好切在切换点上。</b>前三秒 FHD、后三秒 OG2K，裁到白衬衫，让你看得到织纹；'
 '标签是拍摄的人自己烧进画面的。OG2K 之下织纹是细而均匀的交叉纹，那就是这块布本来的样子；'
 'FHD 之下它变粗、变花，而且出现的图案并不是镜头前那一个。',
 '<b>六秒,正好切在切換點上。</b>前三秒 FHD、後三秒 OG2K,裁到白襯衫,讓你看得到織紋;'
 '標籤是拍攝的人自己燒進畫面的。OG2K 之下織紋是細而均勻的交叉紋,那就是這塊布本來的樣子;'
 'FHD 之下它變粗、變花,而且出現的圖案並不是鏡頭前那一個。') + '''
  </figcaption>
</figure>

'''

B += h2('Grading the banding', '把横向条带打分', '把橫向條帶打分', 'banding')
B += p('The banding can be graded on its own. Take a real frame, shrink it with the recipes '
       'a route actually uses, shrink it again with the average of those same recipes, and '
       'subtract. What is left is the banding by itself.',
       '横向条带可以单独打分。拿一张真实画面，用某条路线实际会用到的做法缩一次，'
       '再用那些做法自己的平均缩一次，两者相减。剩下的就是条带本身。',
       '橫向條帶可以單獨打分。拿一張真實畫面,用某條路線實際會用到的做法縮一次,'
       '再用那些做法自己的平均縮一次,兩者相減。剩下的就是條帶本身。')
B += table(
  [('t','route','路线','路線'), ('n','recipes','用几套','用幾套'),
   ('n','size of it','有多大','有多大'), ('n','worst row vs best','最重行比最轻行','最重列比最輕列'),
   ('n','grade','评分','評分')],
  [('hl',[('<b>OG3K, OG2K</b> &mdash; no resizer','<b>OG3K、OG2K</b> —— 不经过','<b>OG3K、OG2K</b> —— 不經過'),
          '&mdash;','<b>0.00%</b>','<b>1.0&times;</b>','<b>A</b>']),
   ('hl',[('shrink by a whole number','缩整数倍','縮整數倍'),'1','<b>0.00%</b>','1.0&times;','<b>A</b>']),
   ('',[('OG4K &mdash; shrink 3/2','OG4K —— 缩 3/2','OG4K —— 縮 3/2'),'2','16.9%','1.0&times;','B']),
   ('bad',[('UHD','UHD','UHD'),'<b>16</b>','19.9%','8.9&times;','<b>D</b>']),
   ('bad',[('<b>FHD</b>','<b>FHD</b>','<b>FHD</b>'),'<b>16</b>','<b>21.0%</b>','<b>13&ndash;22&times;</b>','<b>F</b>'])])
B += p('A control makes this readable: feed the same test a picture of pure random noise '
       'and both directions come out identical, 3.2 against 3.4. Feed it a real scene and '
       'rows vary by 13&times; while columns vary by under 3&times;. <b>The lopsidedness '
       'comes from the subject, not the circuit</b> &mdash; a real frame carries more fine '
       'detail across than down, so it is the row recipes that get provoked, and their '
       'mistakes arrive as full-width bands. On hard edges and lettering it reaches '
       '36&times;.',
       '有个对照组让这张表读得懂：同一个测试喂纯随机噪声进去，两个方向的结果一模一样，'
       '3.2 对 3.4。喂真实画面进去，行之间差 13 倍，列之间不到 3 倍。'
       '<b>这个不对称来自题材，不是来自电路</b> —— 真实画面横向的细节比纵向多，'
       '所以被激发的是「行」那一组做法，而它的错误是整行宽的。'
       '在硬边和文字上，这个比值到 36 倍。',
       '有個對照組讓這張表讀得懂:同一個測試餵純隨機雜訊進去,兩個方向的結果一模一樣,'
       '3.2 對 3.4。餵真實畫面進去,列之間差 13 倍,行之間不到 3 倍。'
       '<b>這個不對稱來自題材,不是來自電路</b> —— 真實畫面橫向的細節比縱向多,'
       '所以被激發的是「列」那一組做法,而它的錯誤是整列寬的。'
       '在硬邊和文字上,這個比值到 36 倍。')

B += h2('Is FHD better in the dark?', 'FHD 暗部比较好吗？', 'FHD 暗部比較好嗎?', 'lowlight')
B += p('It looks like it. FHD averages about twice as many sensor cells per output pixel as '
       'OG2K, which is half a stop, and in real footage it does measure quieter. But '
       'averaging more cells is also what makes a picture soft, and a soft picture looks '
       'less noisy whether or not it collected more light. So: blur the sharper mode until '
       'its texture matches FHD&rsquo;s, then compare.',
       '看起来是。FHD 每个输出像素平均到的格子数大约是 OG2K 的两倍，也就是半级，'
       '而在实拍上它确实量起来比较安静。但「平均更多格子」同时也是让画面变软的原因，'
       '而软的画面看起来就是比较不吵，不管它有没有真的多收到光。'
       '所以：把比较锐的那个模式模糊到纹理跟 FHD 一样，再比。',
       '看起來是。FHD 每個輸出像素平均到的格子數大約是 OG2K 的兩倍,也就是半級,'
       '而在實拍上它確實量起來比較安靜。但「平均更多格子」同時也是讓畫面變軟的原因,'
       '而軟的畫面看起來就是比較不吵,不管它有沒有真的多收到光。'
       '所以:把比較銳的那個模式模糊到紋理跟 FHD 一樣,再比。')
B += table(
  [('t','','',''), ('n','texture','纹理','紋理'), ('n','noise','噪点','雜訊'), ('n','vs FHD','相对 FHD','相對 FHD')],
  [('',[('OG2K, untouched','OG2K，原样','OG2K,原樣'),'<b>16.7%</b>','7.14','&times;1.25']),
   ('hl',[('<b>OG2K, blurred to match FHD</b>','<b>OG2K，模糊到跟 FHD 一样</b>','<b>OG2K,模糊到跟 FHD 一樣</b>'),
          '14.0%','<b>5.77</b>','<b>&times;1.01</b>']),
   ('ref',[('<i>FHD, as shot</i>','<i>FHD，原样</i>','<i>FHD,原樣</i>'),'<i>14.3%</i>','<i>5.71</i>','<i>&mdash;</i>'])])
B += p('<b>Matched for sharpness they are level.</b> A second scene, shot at ISO&nbsp;800, '
       'says it harder: take the OG3K frame, shrink it properly to FHD&rsquo;s size with a '
       'filter that <em>does</em> smooth first, and you get the same noise with more than '
       'twice the texture &mdash; no blurring needed at all. <b>FHD&rsquo;s half stop is '
       'the blur, not the light.</b> You can have the same trade from a sharper mode '
       'whenever you want it, and stop before it costs you the detail.',
       '<b>锐利度对齐之后两者持平。</b>另一个 ISO&nbsp;800 的场景讲得更重：'
       '拿 OG3K 的画面，用一个<em>会</em>先平滑的滤波器正确缩到 FHD 的尺寸，'
       '得到的是一样的噪点、两倍以上的纹理 —— 连模糊都不用。'
       '<b>FHD 那半级是模糊，不是光。</b>同样的交换你随时可以自己做，'
       '而且可以在还没赔掉细节之前停手。',
       '<b>銳利度對齊之後兩者持平。</b>另一個 ISO&nbsp;800 的場景講得更重:'
       '拿 OG3K 的畫面,用一個<em>會</em>先平滑的濾波器正確縮到 FHD 的尺寸,'
       '得到的是一樣的雜訊、兩倍以上的紋理 —— 連模糊都不用。'
       '<b>FHD 那半級是模糊,不是光。</b>同樣的交換你隨時可以自己做,'
       '而且可以在還沒賠掉細節之前停手。')

B += h2('So what should you shoot?', '所以该拍哪个', '所以該拍哪個', 'pick')
B += table(
  [('t','you are shooting','你在拍的是','你在拍的是'), ('t','take','选','選'), ('t','why','理由','理由')],
  [('hl',[('<b>anything, if the size suits you</b>','<b>任何东西，只要尺寸合用</b>','<b>任何東西,只要尺寸合用</b>'),
          ('<b>OG3K</b>','<b>OG3K</b>','<b>OG3K</b>'),
          ('never touches the resizer; the cleanest route measured','完全不碰缩图电路，量过最干净的一条','完全不碰縮圖電路,量過最乾淨的一條')]),
   ('hl',[('<b>2K &mdash; fabric, skin, foliage</b>','<b>2K —— 布料、皮肤、植物</b>','<b>2K —— 布料、皮膚、植物</b>'),
          ('<b>OG2K</b>','<b>OG2K</b>','<b>OG2K</b>'),
          ('2.3&times; cleaner than FHD on everyday material, and no banding','一般素材上比 FHD 干净 2.3 倍，而且没有条带','一般素材上比 FHD 乾淨 2.3 倍,而且沒有條帶')]),
   ('',[('2K &mdash; fine repeating texture','2K —— 细密的重复花纹','2K —— 細密的重複花紋'),
        ('FHD','FHD','FHD'),
        ('its &divide;2 stage is exactly the right filter for once','它的 &divide;2 那一关刚好是对的滤波器','它的 &divide;2 那一關剛好是對的濾波器')]),
   ('',[('4K','4K','4K'),
        ('full read, shrink <b>3/2</b>','读满，缩 <b>3/2</b>','讀滿,縮 <b>3/2</b>'),
        ('beats UHD on false patterns, and only two recipes','假花纹赢现行 UHD，而且只用两套做法','假花紋贏現行 UHD,而且只用兩套做法')]),
   ('bad',[('2K &mdash; in the dark','2K —— 暗部','2K —— 暗部'),
           ('<b>still OG2K</b>','<b>还是 OG2K</b>','<b>還是 OG2K</b>'),
           ('FHD&rsquo;s advantage is blur; soften it yourself instead','FHD 的优势是模糊，不如自己去软化','FHD 的優勢是模糊,不如自己去軟化')])])
B += p('<b>And for anyone building a new recording mode:</b> pick a shrink ratio whose '
       'bottom number is five or less &mdash; 3/2, 5/2, 8/5, 12/5, or a whole number. It '
       'costs nothing, and the banding never appears. That is the one thing on this page '
       'that can be applied without measuring anything else.',
       '<b>如果你在做新的录制模式：</b>挑一个分母小于等于 5 的缩图比例 —— '
       '3/2、5/2、8/5、12/5，或整数。这不花任何代价，而条带就不会出现。'
       '这是这一页唯一一条不用再量任何东西就能直接用的规则。',
       '<b>如果你在做新的錄製模式:</b>挑一個分母小於等於 5 的縮圖比例 —— '
       '3/2、5/2、8/5、12/5,或整數。這不花任何代價,而條帶就不會出現。'
       '這是這一頁唯一一條不用再量任何東西就能直接用的規則。', cls='note')

B += h2('Where this comes from', '这些是怎么来的', '這些是怎麼來的', 'sources')
B += p('The sixteen recipes were solved from <b>seven stills shot and released by Jose</b> '
       '&mdash; one frame per mode of the same scene, on one body and one firmware. Nothing '
       'else went into them.',
       '那十六套做法，是从 <b>Jose 拍摄并公开的七张静态照片</b>解出来的 —— '
       '一个模式一张，同场景，同一台机身、同一版固件。里面没有放进别的东西。',
       '那十六套做法,是從 <b>Jose 拍攝並公開的七張靜態照片</b>解出來的 —— '
       '一個模式一張,同場景,同一台機身、同一版韌體。裡面沒有放進別的東西。')
B += p('<b>The footage used to check the results is separate, and is not Jose&rsquo;s.</b> '
       'The sailor-uniform clip above, the clothing pair, the star chart and the night test '
       'were all shot by this project. They are used only to confirm or contradict what the '
       'seven stills predict. Twice they contradicted it, and the page was changed.',
       '<b>用来检查结果的实拍素材是另一回事，而且不是 Jose 的。</b>'
       '上面那段水手服、衣物那一对、星图和夜景测试，全部是本项目自己拍的。'
       '它们只用来确认或推翻那七张照片的预测。有两次它们推翻了，页面就改了。',
       '<b>用來檢查結果的實拍素材是另一回事,而且不是 Jose 的。</b>'
       '上面那段水手服、衣物那一對、星圖和夜景測試,全部是本專案自己拍的。'
       '它們只用來確認或推翻那七張照片的預測。有兩次它們推翻了,頁面就改了。')
B += p('<b>Still open:</b> the sixteen recipes were only ever solved at one shrink ratio, '
       '25/16. Everything here about 3/2 and the whole numbers assumes the same sixteen are '
       'used at every ratio. 3/2 needs only two of them and both were measured directly, so '
       'that is the least risky assumption on the page &mdash; but it is still an '
       'assumption. One clip recorded through 3/2 would settle it.',
       '<b>还没解：</b>那十六套做法只在一个缩图比例上解过，就是 25/16。'
       '这里所有关于 3/2 和整数倍的说法，都假设每个比例用的是同一组十六套。'
       '3/2 只需要其中两套，而那两套都是直接量到的，所以这是全页风险最小的假设 —— '
       '但它仍然是假设。录一段走 3/2 的片子就能定案。',
       '<b>還沒解:</b>那十六套做法只在一個縮圖比例上解過,就是 25/16。'
       '這裡所有關於 3/2 和整數倍的說法,都假設每個比例用的是同一組十六套。'
       '3/2 只需要其中兩套,而那兩套都是直接量到的,所以這是全頁風險最小的假設 —— '
       '但它仍然是假設。錄一段走 3/2 的片子就能定案。', cls='note')
B += p('The stage <em>before</em> this one &mdash; what the sensor itself does &mdash; is a '
       'separate page: <a href="imx410-binning.html">What the IMX410&rsquo;s binning '
       'actually does</a>. The full technical version of both, with every table, is '
       '<a href="reduction-kernels.html">here</a>.',
       '这一关<em>之前</em>那一关 —— 感光元件自己做了什么 —— 在另一页：'
       '<a href="imx410-binning.html">IMX410 的像素合并到底做了什么</a>。'
       '两者的完整技术版、所有表格，在<a href="reduction-kernels.html">这里</a>。',
       '這一關<em>之前</em>那一關 —— 感光元件自己做了什麼 —— 在另一頁:'
       '<a href="imx410-binning.html">IMX410 的像素合併到底做了什麼</a>。'
       '兩者的完整技術版、所有表格,在<a href="reduction-kernels.html">這裡</a>。')

print('built', build('rwzm-resampler.html', META, B), 'bytes')
