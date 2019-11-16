import logging
import os
import re
import socket
import uuid
import xml.etree.ElementTree as ET
from collections import Counter

import requests
from requests_html import HTMLSession
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters

import config

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

updater = Updater(token=config.telegram_token, request_kwargs=config.proxy)
pattern = re.compile(config.host_name_pattern)
dispatcher = updater.dispatcher

errors = {
    'INCORRECT_DOMAIN_NAME': 'Попробуйте короткое DNS имя, например vl44-srv03',
    'PARSE_ERROR': 'Не найдены элементы на странице',
    'CANT_SAVE_XML': 'Не удалось сформировать XML',
    'ONLINE_NA': 'В сети, УТМ недоступен',
    'OFFLINE': 'Не в сети',
    'NO_UTMS': 'Не найдено УТМ',
}


class Utm:
    """ УТМ сервер """

    def __init__(self, hostname: str):
        self.hostname: str = hostname

    def get_domain_name(self) -> str:
        return self.hostname + config.domain

    def get_utm_url(self) -> str:
        return f'http://{self.get_domain_name()}:8080'

    def get_version_url(self) -> str:
        return f'{self.get_utm_url()}/?b'

    def get_reset_filter_url(self) -> str:
        return f'{self.get_utm_url()}/xhr/filter/reset'

    def get_diagnosis_url(self) -> str:
        return f'{self.get_utm_url()}/diagnosis'

    def get_query_clients_url(self) -> str:
        return f'{self.get_utm_url()}/opt/in/QueryClients_v2'


class Result:
    """ Результаты опроса УТМ
    С главной страницы получаем:
    * Состояние УТМ и лицензии
    * Сроки ключей ГОСТ, PKI
    * Состояние чеков
    * Организация из сертификата ГОСТ

    Фиксируются все ошибки при парсинге
    """

    def __init__(self, utm: Utm):
        self.utm: Utm = utm
        self.host: str = utm.hostname
        self.url: str = utm.get_utm_url()
        self.legal: str = ''
        self.gost: str = ''
        self.pki: str = ''
        self.cheques: str = ''
        self.fsrar: str = ''
        self.title: str = ''
        self.sign: bool = False
        self.status: bool = False
        self.licence: bool = False
        self.filter: bool = False
        self.error: list = []
        self.docs_in: int = 0
        self.docs_out: int = 0


def check_docs_count(res: Result):
    """ Подсчет входящих, исходящих документов для диагностики связи УТМ"""

    def count_html_elements(url: str, elem: str) -> int:
        page = requests.get(url, timeout=2).text
        counter = len(ET.fromstring(page).findall(elem))
        return counter

    docs_in, docs_out, error = '', '', ''
    url_utm = res.utm.get_utm_url()
    url_in = url_utm + '/opt/out/waybill_v3'
    url_out = url_utm + '/opt/in'
    html_element = 'url'
    print(url_in, url_out)

    try:
        res.docs_in = count_html_elements(url_in, html_element)
        res.docs_out = count_html_elements(url_out, html_element)

    except (requests.ConnectionError, requests.ReadTimeout):
        error = check_utm_availability(res.utm.get_domain_name())

    except ET.ParseError:
        error = errors.get('PARSE_ERROR')

    res.error.append(error)
    return res


def get_servers(filename):
    """ Список УТМ из хостов """
    with open(filename) as f:
        data = f.read().splitlines()
        return [Utm(server) for server in set(data)]


def get_md_text(filename: str) -> str:
    """ Представление файлов для справки """
    with open(filename, 'r', encoding='utf-8') as file:
        return file.read()


def check_rdp(host: str) -> bool:
    """ Проверка доступности сервера по RDP"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect((host, 3389))
        s.shutdown(2)
        return True
    except (ConnectionRefusedError, socket.gaierror):
        return False


def check_utm_availability(host: str):
    """ Проверка не доступен УТМ или хост"""
    return errors.get('ONLINE_NA') if check_rdp(host) else errors.get('OFFLINE')


def add_backticks_to_list(results: list) -> list:
    """ Обрамление в код для моноширных списков """
    backticks = '```'
    results.insert(0, backticks)
    results.insert(len(results), backticks)
    return results


def split_in_lines(results: list) -> str:
    """ Построчный вывод списков """
    return '\n'.join(results)


def get_quick_check(utm: Utm) -> Result:
    """ Быстрая диагностика УТМ """
    result: Result = Result(utm)

    try:
        res = requests.get(utm.get_diagnosis_url(), timeout=3)
        result.fsrar = ET.fromstring(res.text).find('CN').text

    except (requests.ConnectionError, requests.ReadTimeout):
        result.error.append(check_utm_availability(utm.get_domain_name()))

    return result


def check_sign(res: Result):
    """ Создание и попытка отправки XML для подтверждения работы механизма подписи"""
    create_result, filename = make_query_clients_xml(res.fsrar)
    if create_result:
        res.error.append(create_result)

    send_result = send_query_clients_xml(res.utm, filename)
    if send_result:
        res.error.append(send_result)
    else:
        res.sign = True

    return res


def make_query_clients_xml(fsrar: str):
    """ Создание XML """
    err = None
    filename = None

    try:
        tree = ET.parse(config.queryclients_xml)
        root = tree.getroot()
        root[0][0].text, root[1][0][0][0][1].text = fsrar, fsrar
        filename = uuid.uuid4().__str__() + '.xml'
        tree.write(filename)
    except:
        err = errors.get('CANT_SAVE_XML')
    return err, filename


def send_query_clients_xml(utm: Utm, filename: str):
    """ Отправка XML """
    err = None

    try:
        files = {'xml_file': (filename, open(filename, 'rb'), 'application/xml')}
        r = requests.post(utm.get_query_clients_url(), timeout=5, files=files)
        print(r)
        if ET.fromstring(r.text).find('sign') is None:
            err = ET.fromstring(r.text).find('error').text
        os.remove(filename)
    except requests.ConnectionError:
        err = check_utm_availability(utm.get_domain_name())

    return err


def check_utm_indexpage(res: Result):
    """ Основная диагностика """
    session = HTMLSession()

    try:
        index = session.get(res.utm.get_version_url())
        home_data = index.html.find('#home', first=True)
        home = home_data.text.split('\n')

        # Проверка статус и лицензии
        if 'Проблема с RSA' not in home:
            res.status = True

        if 'Лицензия на вид деятельности действует' in home:
            res.license = True

        if 'Обновление настроек не требуется' in home:
            res.filter = True

    except (requests.ConnectionError, requests.ReadTimeout):
        res.error.append('Не удатся получить страницу УТМ')

    except:
        res.error.append(errors.get('PARSE_ERROR'))

    return res


def start_command(bot, update):
    bot.send_message(chat_id=update.message.chat_id, text='Введите сервер с УТМ для проверки')


def help_command(bot, update):
    bot.send_message(chat_id=update.message.chat_id, text=get_md_text('help.md'), parse_mode='Markdown')


def faq_command(bot, update):
    bot.send_message(chat_id=update.message.chat_id, text=get_md_text('faq.md'), parse_mode='Markdown')


def filter_command(bot, update):
    """ Обновление настроек и фильтров на всех УТМ
    После команды можно указать список УТМ хостов через пробел
    Если не указаны хосты, то выполняется на всех УТМ по списку
    """
    args = update.message.text.split()
    args.pop(0)

    utms = get_servers(config.utmlist) if args == ['all'] else [Utm(arg) for arg in set(args) if pattern.match(arg)]
    if utms:
        results = {}
        for utm in utms:
            try:
                result = requests.get(utm.get_reset_filter_url(), timeout=3).text

            except (requests.ConnectionError, requests.ReadTimeout):
                result = check_utm_availability(utm.get_domain_name())

            results[utm.hostname] = result.strip()

        res_keys = Counter(results.values())

        res_text = [f'{res[0]} {res[1]}' for res in sorted(results.items(), key=lambda l: l[1])]
        res_text = add_backticks_to_list(res_text)
        res_text.extend([f'`{k}: {v}`' for k, v in dict(res_keys).items()])

    else:
        res_text = [errors.get('NO_UTMS'), ]

    bot.send_message(chat_id=update.message.chat_id, text=split_in_lines(res_text), parse_mode='Markdown')


def status_command(bot, update):
    utms = get_servers(config.utmlist)
    results = [get_quick_check(utm) for utm in utms]
    results.sort(key=lambda utm: utm.error)
    err_counter = len([utm for utm in results if utm.error != []])
    res_counter = len(results) - err_counter

    text_res = [f'{res.host.ljust(11)} {"[" + res.fsrar + "] OK" if not res.error else " ".join(res.error)}' for res in
                results]
    text_res = add_backticks_to_list(text_res)
    text_res.insert(len(text_res), f'`OK: {res_counter} Errors: {err_counter}`')

    bot.send_message(chat_id=update.message.chat_id, text=split_in_lines(text_res), parse_mode='Markdown')


def text_message(bot, update):
    """ Диагностика УТМ по указаноому hostname"""
    utm_server = update.message.text
    if pattern.match(utm_server):
        res = get_quick_check(Utm(utm_server))
        comments = {
            'fsrar': 'УТМ недоступен',
            'licence': 'Не действительна',
            'sign': 'Не удалось подписать документ,проверьте Рутокен',
            'filter': 'Необходимо обновить настройки',
            'docs_in': 'Возможно, проблема обмена Супермаг',
            'docs_out': 'Возможно, нет связи с ФСРАР',
        }

        if res.fsrar:
            check_sign(res)
            check_docs_count(res)
            check_utm_indexpage(res)

        response = list()
        response.append(f'УТМ:        {res.host}')
        response.append(f'ФСРАР:      {res.fsrar if res.fsrar else comments.get("fsrar")}')
        response.append(f'Рутокен:    {"OK" if res.sign else comments.get("sign")}')
        response.append(f'Лицензия:   {"OK" if res.licence else comments.get("licence")}')
        response.append(f'Фильтр:     {"OK" if res.filter else comments.get("filter")}')
        response.append(f'Входящие:   {res.docs_in} {"OK" if res.docs_in <= 5 else comments.get("docs_in")}')
        response.append(f'Исходящие:  {res.docs_out} {"OK" if res.docs_out <= 5 else comments.get("docs_out")}')
        response.append(f'Ошибки:     {"ОК" if res.error else " ".join([e for e in res.error if e])}')

        add_backticks_to_list(response)
    else:
        response = errors.get('INCORRECT_DOMAIN_NAME')
    bot.send_message(chat_id=update.message.chat_id, text=split_in_lines(response), parse_mode='Markdown')


faq_command_handler = CommandHandler('faq', faq_command)
help_command_handler = CommandHandler('help', help_command)
start_command_handler = CommandHandler('start', start_command)
status_command_handler = CommandHandler('status', status_command)
filter_command_handler = CommandHandler('filter', filter_command)
text_message_handler = MessageHandler(Filters.text, text_message)

dispatcher.add_handler(start_command_handler)
dispatcher.add_handler(text_message_handler)
dispatcher.add_handler(help_command_handler)
dispatcher.add_handler(faq_command_handler)
dispatcher.add_handler(status_command_handler)
dispatcher.add_handler(filter_command_handler)

updater.start_polling(clean=True)

updater.idle()
