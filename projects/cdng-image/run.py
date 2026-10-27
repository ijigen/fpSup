import sys
if __name__=='__main__':
    if len(sys.argv)>1:
        from cdng_image.cli import main
        main()
    else:
        from cdng_image.gui import main
        main()
