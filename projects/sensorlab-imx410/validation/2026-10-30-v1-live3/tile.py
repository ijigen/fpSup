import sys
from PIL import Image
S='/private/tmp/claude-501/-Users-dido-Developer-localized-SIGMAfp-re/f58271b0-5db4-4cd7-a9d1-abe4b221a3ba/scratchpad/'
im=Image.open(sys.argv[1]).crop((0,80,1024,300)).resize((512,110)); im.save(S+'tile.png')
