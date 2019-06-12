Для того, чтобы chgksuite работало на вашем Python, необходимо установить пакеты из файла `requirements`: `pip install -r requirements`. Если у вас Windows и не настроена как надо сборка c-extensions, лучше пользуйтесь [Anaconda](https://www.continuum.io/downloads) и перед тем, как ставить остальные требуемые модули, `conda install lxml`.

Под OS X тоже возможны сложности с `lxml`, для решения воспользуйтесь этим [рецептом со StackOverflow](https://stackoverflow.com/a/26544099/4328153) (у вас должен быть установлен [homebrew](http://brew.sh/)):

```
brew install libxml2
brew install libxslt
brew link libxml2 --force
brew link libxslt --force
```

Работа с более ранними или поздними версиями пакетов возможна, но не гарантируется. Точно будут проблемы со старыми версиями PyDocX.

Если вы хотите собирать бинарные версии и тестировать, вам также потребуются зависимости из `requirements_dev`: `pip install -r requirements_dev`.

Чтобы собрать:

```
pyi-makespec --hidden-import=PIL --additional-hooks-dir=. --onefile chgksuite.py
pyinstaller chgksuite.spec
```

Чтобы запустить тесты: `py.test`.

Чтобы получить готовые к работе архивы для win и mac, из папки `dist` можно запустить `package.sh`, указав идентификатор версии в переменной окружения `VERSION`. В папке dist при этом должны лежать бинарные файлы `chgksuite` и `chgksuite.exe`.
