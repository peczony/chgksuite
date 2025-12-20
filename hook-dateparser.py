from PyInstaller.utils.hooks import exec_statement, collect_submodules

# taken from here: https://github.com/pyinstaller/pyinstaller/issues/3429#issuecomment-379723204
# the official hook in pyinstaller/master doesn't work

strptime_data_file = exec_statement(
    "import inspect; import _strptime; print(inspect.getfile(_strptime))"
)

datas = [(strptime_data_file, ".")]

hiddenimports = collect_submodules("dateparser")
