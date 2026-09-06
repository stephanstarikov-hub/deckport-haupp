# DeckPort VPN — техническое руководство

VPN-плагин для Decky Loader: подписка → сервер → Connect прямо в Quick Access Menu.
Системный TUN работает в backend независимо от того, открыто ли меню Decky.

**Статус:** реализация MVP собрана, прошла автоматические проверки и настоящий
TUN-тест в изолированном Linux namespace. Проверка на Steam Deck LCD/OLED,
SteamOS Gaming Mode и реальном VPN-провайдере ещё не проведена. По критериям ТЗ
аппаратная приёмка MVP остаётся открытой.

## Реализовано

- Современные `@decky/api` (`callable`, события), `@decky/ui`, React/TypeScript.
- Root Python-backend, асинхронный запуск sing-box и независимый supervisor.
- HTTPS-подписки: добавление, сохранение, обновление, редактирование, удаление.
- URI lists, base64 lists, Clash YAML/JSON, sing-box JSON, одно-peer WireGuard INI.
- VLESS (TLS, Reality, Vision), VMess, Trojan, Shadowsocks, SOCKS5, WireGuard endpoint.
- TCP, WebSocket, gRPC, базовый HTTP transport; конфигурацию проверяет core.
- Список серверов, поиск, выбор и сохранение последнего выбора; метаданные подписки.
- Connect, отмена подключения, Disconnect, backend-состояние, события + resync.
- IPv4/IPv6 TUN, DNS hijack, DNS-over-HTTPS через выбранный VPN.
- Проверка системного маршрута и public IP до/после подключения, несколько IP-сервисов.
- Безопасные логи и копирование диагностики без credentials.
- Установочный ZIP с Linux x86_64 core; pacman-пакеты устанавливать не нужно.

Phase 2–4 (избранное, ping, сортировки, auto-reconnect, auto-connect,
sleep/resume recovery, статистика, kill switch, split tunneling) не заявлены
как выполненные. В этой версии нет kill switch: при падении VPN cleanup
восстанавливает обычное соединение. Переподключение выполняется вручную.

## Архитектура

```text
src/
  index.tsx                   QAM, состояния, выбор сервера
  api/index.ts                типизированные RPC
  components/                 формы и диагностика
main.py                       Decky lifecycle и RPC boundary
vpn/
  service.py                  source of truth, задачи, монитор процесса
  storage.py                  приватная атомарная запись JSON
  network.py                  внешняя HTTPS-проверка
  subscription/
    fetch.py                  bounded HTTPS, IP validation, redirects
    detect.py / parser.py     определение формата и диспетчер
    model.py                  закрытая схема, нормализация, public DTO
    parsers/                  URI, base64, Clash, sing-box, WireGuard
  core/
    config.py                 конфигурация sing-box 1.14.0
    process.py                async check/start/stop
    guardian.py               владелец core, cleanup при потере backend
backend/bin/sing-box           bundled ELF linux/amd64
py_modules/yaml/               bundled pure-Python PyYAML
scripts/                      сборка, упаковка, реальные core/TUN-проверки
tests/                        парсеры, безопасность, backend lifecycle
licenses/                     сторонние лицензии
release/                      установочный ZIP, SHA-256, исходники
```

Официальный Decky template изучен по revision
`90d0780e882a17f5714fc6de044c645f22608290`. Сохранены entrypoint,
manifest/API version, Rollup-конфигурация и схема плагина. `_root` даёт
backend права. Не используются `serverAPI.callPluginMethod` или старый
`decky-frontend-lib` import. Зависимости зафиксированы lockfile.

Выбран sing-box **1.14.0**, стабильный релиз на момент разработки. Он
объединяет требуемые протоколы, TUN и DNS; WireGuard использует `endpoints`,
DNS — современные typed servers. Frontend не запускает системные команды.

## Установка готового ZIP

1. На Steam Deck уже должен быть установлен актуальный Decky Loader.
2. Возьмите `release/decky-vpn-0.1.0.zip`, включающий core и Python-зависимости.
3. В настройках Decky включите Developer Mode и используйте установку плагина
   из ZIP. Если ваша версия предлагает только установку по URL, разместите ZIP
   по доступному HTTPS-адресу и используйте **Install Plugin from URL**.
   ZIP здесь не опубликован в интернете автоматически.
4. Decky VPN → **+ Add subscription** → имя и HTTPS URL → **Add**.
5. **Server** → выберите сервер → **Connect**. Дождитесь `CONNECTED`.
6. Закройте QAM, запустите игру. Для отключения снова откройте Decky VPN
   и нажмите **Disconnect**.

Ввод использует Steam TextField и экранную клавиатуру. URL скрыт в форме;
при редактировании пустое поле сохраняет существующую ссылку. Кнопки Decky
поддерживают gamepad focus; B возвращает из внутренних экранов, модальные
окна закрываются B. D-pad, стик, A/B и touchscreen требуют аппаратной приёмки.

Для ручного developer deployment содержимое `decky-vpn/` из ZIP поместите
в `~/homebrew/plugins/decky-vpn/`, затем перезагрузите плагин в Decky.
Установка sing-box и изменение read-only областей SteamOS не нужны.

## Сборка

На машине разработчика: Node.js 22+, pnpm 9+, Python 3.10+.
Linux smoke test требует Linux, root, iproute2 и `/dev/net/tun`.

```sh
pnpm install --frozen-lockfile
python scripts/fetch_deps.py
pnpm typecheck
pnpm build
python -m unittest discover -s tests -v
python scripts/check_core.py
python scripts/package.py
```

На Windows перед core check: `python scripts/fetch_deps.py --windows-checker`.
Тестовый Windows core хранится только в `.cache` и не попадает в плагин.
`fetch_deps.py` проверяет фиксированные SHA-256 core и PyYAML. Core скачивается
при сборке, никогда из подписки и никогда при Connect.

```sh
sudo unshare --net --mount --mount-proc python3 -u scripts/linux_smoke.py
```

Тест отказывается работать в host network/mount namespace. Создаёт локальный
SOCKS peer, отправляет настоящий TCP-запрос через системный TUN, проверяет
Disconnect, SIGKILL core, EOF backend pipe и восстановление после SIGKILL
guardian. Интернет и реальная подписка ему не нужны.

## Маршрутизация, DNS и cleanup

sing-box владеет `deckyvpn0`, таблицей **20777** и зарезервированными
приоритетами правил **17770–17789**. Перед подключением проверяются конфликты.
Используются `auto_route`, `strict_route`, `route.auto_detect_interface`.
В MVP `auto_redirect=false`: ограниченная область cleanup без nftables.
Произвольные LAN bypass или UID exclusions не добавляются; служебный
локальный трафик ОС сохраняется.

IPv4 и IPv6 попадают в TUN. Если провайдер не поддерживает IPv6 или UDP,
такие соединения могут не работать; direct fallback для них не добавляется.
SOCKS5 peer должен поддерживать UDP ASSOCIATE для UDP-игр. WireGuard должен
иметь IPv4 default AllowedIPs; IPv6 без соответствующего peer route недоступен.

Адрес VPN-сервера разрешается до установки TUN. Этот bootstrap lookup может
выполняться через обычный системный DNS. Затем используется IP endpoint с
сохранением TLS SNI, direct DNS resolver не добавляется. DNS приложений
перехватывается sing-box. Cloudflare DoH проходит через VPN, при провале
первой проверки выполняется повтор с Quad9 DoH. Нативная DNS-интеграция
sing-box 1.14 относится к TUN link; `/etc/resolv.conf` и постоянные
NetworkManager profiles плагин не редактирует.

`CONNECTED` требует живой core, маршрута к 1.1.1.1 через TUN и успешного
HTTPS IP-check. Используются api.ipify.org, icanhazip.com и
checkip.amazonaws.com; достаточно одного успешного ответа. Одинаковый
IP до/после не считается автоматически ошибкой: возможен общий выходной
адрес. IP-check не заменяет проверку DNS/IPv6/игр на SteamOS.

Core принадлежит guardian с единственным lock. Backend держит pipe открытым.
EOF, включая crash backend, вызывает SIGTERM core, ожидание, при необходимости
SIGKILL и очистку собственных правил/TUN. Linux parent-death signal завершает
core при гибели guardian. Приватный ownership journal позволяет очистить
остатки при следующей загрузке. Чужие таблицы и весь firewall не удаляются.

`DISCONNECTED` показывается только после cleanup. При ошибке остаётся `ERROR`
и доступен повторный Disconnect. Unload/uninstall используют тот же путь.
После reboot временные kernel routes исчезают. Одновременный SIGKILL всех
процессов может потребовать повторного открытия плагина для journal cleanup;
постоянные firewall/systemd правила не устанавливаются.

## Данные и безопасность

- `DECKY_PLUGIN_SETTINGS_DIR/subscriptions.json`: URL, приватные конфигурации,
  метаданные, выбранный сервер; directory 0700, file 0600.
- `DECKY_PLUGIN_RUNTIME_DIR`: generated-config.json (0600, удаляется при stop),
  vpn.pid, guardian.lock, network-owned.json, state.json.
- `DECKY_PLUGIN_LOG_DIR/plugin.log`: только состояния, ротация 128 KiB × 3.

URL и credentials не возвращаются в public DTO. Сырые stderr/stdout core
отбрасываются: они могут содержать секреты. Поэтому диагностика содержит
общее безопасное сообщение о core error, без его полного stderr.
Секреты хранятся локально без шифрования с ограниченными правами; root и
владелец устройства могут их прочитать. За RPC transport и собственные
логи отвечает Decky Loader.

Подписки ограничены 4 MiB и 2000 entries; всего до 30 подписок. HTTPS-only,
port 443, сертификаты проверяются, не более трёх redirects. Private, loopback
и link-local endpoints запрещены. TCP соединяется с проверенным IP с TLS SNI,
исключая DNS rebinding между проверкой и запросом. YAML использует SafeLoader;
aliases, глубокая вложенность, WG hooks, внешние binary/plugin commands и
TLS filesystem references отвергаются. Команды передаются argv без shell.

Не все расширения провайдеров поддерживаются. XHTTP, Hysteria/TUIC,
Shadowsocks plugins, произвольные detours/routing, insecure TLS, несколько
WG peers и PostUp/PreUp не принимаются. Невалидные/неподдерживаемые entries
пропускаются с видимым счётчиком; подписка без пригодных серверов отвергается.
Clash proxy-groups не импортируются: берутся настоящие proxy entries.

## Приёмка на Steam Deck

1. Установить и открыть UI в Gaming Mode на LCD и OLED.
2. Добавить собственную подписку, проверить список и skipped count.
3. Выбрать сервер, Connect; сравнить public IP, нажать Verify connection.
4. Закрыть QAM, запустить браузер/игру; проверить HTTP, HTTPS, UDP и DNS.
5. Снова открыть QAM: состояние должно оставаться реальным `CONNECTED`.
6. Disconnect: обычный IP/DNS восстановлены, TUN и его правила удалены.
7. Повторить 10 циклов, отменить CONNECTING, обновить подписку.
8. Перезапустить Decky/Steam Deck: подписка и выбор сохраняются; auto-connect
   в Phase 1 отсутствует.
9. Проверить unload/uninstall при активном VPN и восстановление сети.
10. Проверить DNS/IPv6 leaks, Wi-Fi смену и сон/пробуждение. При потере связи
    использовать Verify connection и ручное переподключение. Автоматическое
    восстановление и kill switch относятся к следующим фазам.

Read-only команды для developer terminal:

```sh
ip -j route get 1.1.1.1
ip -4 rule show
ip -6 rule show
ip link show deckyvpn0
```

## Официальные источники

- [Decky template](https://github.com/SteamDeckHomebrew/decky-plugin-template)
- [Decky API](https://github.com/SteamDeckHomebrew/loader-api)
- [Decky UI](https://github.com/SteamDeckHomebrew/decky-frontend-lib)
- [sing-box TUN](https://sing-box.sagernet.org/configuration/inbound/tun/)
- [sing-box DNS](https://sing-box.sagernet.org/configuration/dns/)
- [WireGuard endpoint](https://sing-box.sagernet.org/configuration/endpoint/wireguard/)
- [sing-box migrations](https://sing-box.sagernet.org/migration/)

Лицензии: [THIRD_PARTY.md](../THIRD_PARTY.md).
