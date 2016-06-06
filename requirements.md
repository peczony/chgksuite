Для того, чтобы chgksuite работало на вашем Python, необходимо установить следующие пакеты:

```
beautifulsoup4==4.4.1
chardet==2.3.0
html2text==2016.1.8
parse==1.6.6
PyDocX==0.9.5
pyimgur==0.5.2
python-docx==0.8.5
requests==2.8.1
Pillow==3.0.0
ply==3.8
```

Одной командой: `pip install -r requirements`. Если у вас Windows и не настроена как надо сборка c-extensions, лучше пользуйтесь [Anaconda](https://www.continuum.io/downloads) и перед тем, как ставить остальные требуемые модули, `conda install lxml`.

(Работа с более ранними или поздними версиями пакетов возможна, но не гарантируется. Точно будут проблемы со старыми версиями PyDocX.)

Если вы хотите собирать бинарные версии и тестировать, вам также потребуются

```
PyInstaller==3.2
pytest==2.8.4
```

Одной командой: `pip install -r requirements_dev`.

Чтобы собрать: `pyinstaller --onefile chgksuite.py`

Чтобы запустить тесты: `py.test`.
