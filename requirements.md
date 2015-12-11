Для того, чтобы chgksuite работало на вашем Python, необходимо установить следующие пакеты:

```
beautifulsoup4==4.4.1
chardet==2.3.0
html2text==2015.6.21
lxml==3.4.4
parse==1.6.6
PyDocX==0.9.5
pyimgur==0.5.2
python-docx==0.8.5
requests==2.8.1
Pillow==3.0.0
```

Одной командой: `pip install beautifulsoup4==4.4.1 chardet==2.3.0 html2text==2015.6.21 lxml==3.4.4 parse==1.6.6 PyDocX==0.9.5 pyimgur==0.5.2 python-docx==0.8.5 requests==2.8.1 Pillow==3.0.0`

(Работа с более ранними или поздними версиями пакетов возможна, но не гарантируется. Точно будут проблемы со старыми версиями PyDocX.)

Если вы хотите собирать бинарные версии и тестировать, вам также потребуются 

```
PyInstaller==3.0
pytest==2.8.4
```

Одной командой: `pip install PyInstaller==3.0 pytest==2.8.4`

В PyInstaller 3.0 на Windows есть [баг](https://github.com/pyinstaller/pyinstaller/issues/1584), мешающий сборке. Его можно полечить, установив dev-версию (в которой, разумеется, могут быть другие, неизвестные баги) или закомментировав строчки, начинающиеся с `excludedimports` в `\PyInstaller\hooks\hook-PIL.py` и `\PyInstaller\hooks\hook-PIL.SpiderImagePlugin.py`.

Чтобы собрать: `pyinstaller --onefile chgksuite.py`  
Чтобы запустить тесты: `py.test`
