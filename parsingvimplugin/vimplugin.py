def _load_pythonparser() -> None:
    global parsingvimplugin

    import os
    import sys

    import vim

    try:
        this_path = __file__
    except NameError:
        this_path = sys._getframe().f_code.co_filename

    try:
        import parsingvimplugin.codenavigation
    except ImportError:
        sys.path.append(os.path.dirname(os.path.dirname(this_path)))

        import parsingvimplugin.codenavigation

    parsingvimplugin.codenavigation.load_vimplugin(vim)


_load_pythonparser()
del _load_pythonparser
