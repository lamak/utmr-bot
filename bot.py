import logging
import os
import platform
import re
import xml.etree.ElementTree as ET

import requests
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters

import config

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

updater = Updater(token=config.telegram_token, request_kwargs=config.proxy)
dispatcher = updater.dispatcher


class Utm:
    """ УТМ сервер """

    def __init__(self, hostname: str):
        self.hostname: str = hostname

    def get_domain_name(self) -> str:
        return self.hostname + config.domain

    def get_utm_url(self) -> str:
        return f'http://{self.get_domain_name()}:8080'

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
        self.status: bool = False
        self.licence: bool = False
        self.filter: bool = False
        self.error: list = []


errors = {
    'INCORRECT_DOMAIN_NAME': 'Попробуйте короткое DNS имя, например vl44-srv03',
    'PARSE_ERROR': 'Не найдены элементы на странице',
    'CANT_SAVE_XML': 'Не удалось сформировать XML',
    'ONLINE_NA': 'В сети, УТМ недоступен',
    'OFFLINE': 'Не в сети',
}


def get_docs_count(utm: Utm):
    """ Подсчет входящих, исходящих документов для диагностики связи УТМ"""

    docs_in, docs_out, error = '', '', ''
    url_utm = utm.get_utm_url()
    url_in = url_utm + '/opt/out/waybill_v3'
    url_out = url_utm + '/opt/in'
    html_element = 'url'

    def count_html_elements(url: str, elem: str) -> int:
        return len(ET.fromstring(requests.get(url, timeout=2).text).findall(elem))

    try:
        docs_in = count_html_elements(url_in, html_element)
        docs_out = count_html_elements(url_out, html_element)

    except (requests.ConnectionError, requests.ReadTimeout):
        error = check_utm_availability(utm.get_domain_name())

    except ET.ParseError:
        error = errors.get('PARSE_ERROR')

    return docs_in, docs_out, error


def get_domain_name(hostname: str) -> str:
    return hostname + config.domain


def get_utm_url(hostname: str) -> str:
    return f'http://{get_domain_name(hostname)}:8080'


def get_reset_filter_url(hostname: str) -> str:
    return f'{get_utm_url(hostname)}/xhr/filter/reset'


def get_diagnosis_url(hostname: str) -> str:
    return f'{get_utm_url(hostname)}/diagnosis'


def get_query_clients_url(hostname: str) -> str:
    return f'{get_utm_url(hostname)}/opt/in/QueryClients_v2'


def get_md_text(filename: str) -> str:
    with open(filename, 'r', encoding='utf-8') as file:
        return file.read()


def ping(host: str) -> bool:
    # Cross platform ping
    param = {'c': '-n', 'n': 'NUL'} if platform.system().lower() == 'windows' else {'c': '-c', 'n': 'null'}
    return not os.system(f'ping {host} {param["c"]} 2 > {param["n"]}')


def check_utm_availability(host: str):
    """ Проверка не доступен УТМ или хост"""
    return errors.get('ONLINE_NA') if ping(host) else errors.get('OFFLINE')


def get_quick_check(utm: Utm) -> Result:
    """ Быстрая диагностика УТМ """
    result: Result = Result(utm)

    try:
        res = requests.get(utm.get_diagnosis_url(), timeout=3)
        result.fsrar = ET.fromstring(res.text).find('CN').text

    except (requests.ConnectionError, requests.ReadTimeout):
        result.error.append(check_utm_availability(utm.get_domain_name()))

    return result


def make_query_clients_xml(fsrar: str):
    err = None
    try:
        tree = ET.parse(config.queryclients_xml)
        root = tree.getroot()
        root[0][0].text, root[1][0][0][0][1].text = fsrar, fsrar
        tree.write(config.queryclients_xml)
    except:
        err = errors.get('CANT_SAVE_XML')
    return err


def send_query_clients_xml(utm: Utm):
    err = None

    try:
        files = {'xml_file': (config.queryclients_xml, open(config.queryclients_xml, 'rb'), 'application/xml')}
        r = requests.post(utm.get_query_clients_url(), files=files)
        if ET.fromstring(r.text).find('sign') is None:
            err = ET.fromstring(r.text).find('error').text

    except requests.ConnectionError:
        err = check_utm_availability(utm.get_domain_name())

    return err


def start_command(bot, update):
    bot.send_message(chat_id=update.message.chat_id, text='Введите сервер с УТМ для проверки')


def get_servers(filename):
    with open(filename) as f:
        data = f.read().splitlines()
        return [Utm(server) for server in data]


def filter_command(bot, update):
    utms = get_servers(config.utmlist)
    results = []
    for utm in utms:
        try:
            result = requests.get(utm.get_reset_filter_url(), timeout=3).text

        except (requests.ConnectionError, requests.ReadTimeout):
            result = check_utm_availability(utm.get_domain_name())

        results.append(f'{utm.hostname} {result}')

    bot.send_message(chat_id=update.message.chat_id, text='\n'.join(results))


def help_command(bot, update):
    bot.send_message(chat_id=update.message.chat_id, text=get_md_text('help.md'), parse_mode='Markdown')


def faq_command(bot, update):
    bot.send_message(chat_id=update.message.chat_id, text=get_md_text('faq.md'), parse_mode='Markdown')


def status_command(bot, update):
    utms = get_servers(config.utmlist)
    results = [get_quick_check(utm) for utm in utms]
    plaint_res = [f'{res.host} {"[" + res.fsrar + " OK" if not res.error else " ".join(res.error)}' for res in results]

    bot.send_message(chat_id=update.message.chat_id, text='\n'.join(plaint_res))


def text_message(bot, update):
    """ Диагностика УТМ по указаноому hostname"""
    utm_server = update.message.text
    pattern = re.compile(config.host_name_pattern)
    if pattern.match(utm_server):
        result = get_quick_check(Utm(utm_server))
        if not result.error:
            result.error.append(make_query_clients_xml(result.fsrar))
            result.error.append(send_query_clients_xml(result.utm))
        result.error = [e for e in result.error if e]
        response = f'{result.host} {"[" + result.fsrar + "] OK" if not result.error else " ".join(result.error)}'

    else:
        response = errors.get('INCORRECT_DOMAIN_NAME')
    bot.send_message(chat_id=update.message.chat_id, text=response)


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
