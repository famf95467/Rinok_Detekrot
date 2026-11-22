# Плагины FunPay Detector (с версии 1.20.0)

Плагин — папка `plugins/<имя>/` с файлом `plugin.py`. Программа читает все такие папки при запуске. Новый плагин = положить папку и перезапустить программу.
Раздел «Плагины» в интерфейсе: список, включить/выключить, панель плагина, журнал. Все плагины по умолчанию выключены.

Минимальный плагин:

    PLUGIN = {'id': 'demo', 'name': 'Пример', 'version': '1.0', 'description': 'Что делает'}   # id: латиница, цифры, _
    def register(api):
        api.on_orders(lambda rows, now: None)          # строки страницы /orders/trade (из conf_sync, без запросов к сайту)
        api.every(5, lambda: api.log('тик'), 'задание')  # не чаще раза в минуту, только если плагин включён
        api.panel(lambda: {'status': [['Статус', 'ок']]})
        api.action('hello', lambda b: {'note': 'привет'})

Что даёт `api`: `id`, `data_dir` (plugins_data/<id>/, в копии и zip-импорт не входит), `settings()`, `save_settings(dict)`,
`log(text)`, `notify(text)` (Telegram, событие «Сообщения плагинов»), `account(fn)` (запрос к аккаунту через общий замок, паузы и блокировку при капче),
`buyer_node(id)`, `chat_send(node, text)`, `chat_history(node)` (оба только внутри `account`), `as_background()`, `UserError`.

Панель — словарь: `warnings` (список строк), `status` (пары), `settings` (`action`, `fields`: key/label/type bool|int|text|longtext/help/min/max/value),
`forms` (title/help/action/kind text|secret|longtext/label/button; значение приходит в `data['value']`), `buttons`, `tables` (columns, rows: cells + buttons).

Правила: секреты, пароли, ссылки и токены в журнал, ответы панели и оповещения не писать; ошибка плагина не должна ронять программу (она ловится и пишется в журнал плагина).
