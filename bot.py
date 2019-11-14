import re
import os
import logging
import xml.etree.ElementTree as ET
import requests
import config
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

updater = Updater(token=config.telegram_token, request_kwargs=config.proxy)
dispatcher = updater.dispatcher
xml_query = 'query.xml'


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


# todo: свести следующие 2 метода к одному
def get_quick_diagnosis(utm: str):
    try:
        res = requests.get(get_diagnosis_url(utm))
        cn = ET.fromstring(res.text).find('CN').text
        fsrar = 'OK [' + cn + '] ' + utm
    except requests.ConnectionError:
        fsrar = utm + ' **error**'
    except requests.ReadTimeout:
        fsrar = utm + ' **timeout**'
    except ET.ParseError:
        fsrar = utm + ' **no token**'
    return fsrar


def get_fsrar_id(utm: str):
    fsrar, error = '', ''
    try:
        res = requests.get(get_diagnosis_url(utm))
        fsrar = ET.fromstring(res.text).find('CN').text
    except (requests.ConnectionError, requests.ReadTimeout):
        if os.system('ping %s -n 2 > NUL' % (utm,)):
            error = 'Связи нет'
        else:
            error = 'Связь есть, УТМ недоступен'
    except ET.ParseError:
        error = 'Проблема с УТМ, проверьте Рутокен'
    return fsrar, error


def make_query_clients_xml(fsrar: str):
    error = ''
    if fsrar:
        try:
            tree = ET.parse(xml_query)
            root = tree.getroot()
            root[0][0].text, root[1][0][0][0][1].text = fsrar, fsrar
            tree.write(xml_query)
        except:
            error = 'Не удалось сформировать XML'
    return error


def send_query_clients_xml(utm: str):
    status = ''

    try:
        files = {'xml_file': (xml_query, open(
            xml_query, 'rb'), 'application/xml')}
        r = requests.post(get_query_clients_url(utm), files=files)
        if ET.fromstring(r.text).iter('sign'):
            status = 'OK'
        for error in ET.fromstring(r.text).iter('error'):
            status = error.text + ', **проверьте токен**'
    except:
        status = '**Не удалось отправить XML**'
    return status


def startCommand(bot, update):
    bot.send_message(chat_id=update.message.chat_id, text='Введите сервер с УТМ для проверки')


def filterCommand(bot, update):
    with open("utms") as f:
        utms = f.read().splitlines()
    raw_data = []
    for utm in utms:
        try:
            result = requests.get(get_reset_filter_url(utm), timeout=5).text
        except requests.exceptions.ReadTimeout:
            result = 'ConnectionError'
        raw_data.append(utm + " " + result)
    results = '\n'.join([i for i in raw_data])
    bot.send_message(chat_id=update.message.chat_id, text=results)


def helpCommand(bot, update):
    bot.send_message(chat_id=update.message.chat_id, text=get_md_text('help.md'), parse_mode='Markdown')


def faqCommand(bot, update):
    bot.send_message(chat_id=update.message.chat_id, text=get_md_text('faq.md'), parse_mode='Markdown')


def statusCommand(bot, update):
    with open("utms") as f:
        data = f.read().splitlines()
    results = []
    for server in data:
        results.append(get_quick_diagnosis(server))
    results = '\n'.join(results)
    bot.send_message(chat_id=update.message.chat_id, text=results)


def textMessage(bot, update):
    """ Диагностика УТМ по указаноому hostname"""
    utm_server = update.message.text
    pattern = re.compile(config.host_name_pattern)
    if pattern.match(utm_server):
        fsrarid, step1, step2, step3 = '', '', '', ''
        fsrarid, step1 = get_fsrar_id(utm_server)
        if fsrarid:
            step2 = make_query_clients_xml(fsrarid)
            step3 = send_query_clients_xml(utm_server)
        response = ' '.join([utm_server, fsrarid, step1, step2, step3])
    else:
        response = 'Попробуйте короткое DNS имя, например vl44-srv03'
    bot.send_message(chat_id=update.message.chat_id, text=response)


class Utm:
    """ УТМ сервер """

    def __init__(self, hostname: str):
        self.hostname: str = hostname


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
        self.utm: Utm = utm  # fsrar, server, title
        self.legal: str = ''
        self.gost: str = ''
        self.pki: str = ''
        self.cheques: str = ''
        self.status: bool = False
        self.licence: bool = False
        self.error: list = []
        self.fsrar: str = ''
        self.host: str = ''
        self.url: str = ''
        self.title: str = ''
        self.filter: bool = False


def get_docs_count(utm: str):
    """ Подсчет входящих, исходящих документов для диагностики связи УТМ"""

    docs_in, docs_out, error = '', '', ''
    url_utm = get_utm_url(utm)
    url_in = url_utm + '/opt/out/waybill_v3'
    url_out = url_utm + '/opt/in'
    html_element = 'url'

    def count_html_elements(url: str, elem: str) -> int:
        return len(ET.fromstring(requests.get(url, timeout=2).text).findall(elem))

    try:
        docs_in = count_html_elements(url_in, html_element)
        docs_out = count_html_elements(url_out, html_element)

    except (requests.ConnectionError, requests.ReadTimeout):
        if os.system('ping %s -n 2 > NUL' % (utm,)):
            error = 'Связи нет'
        else:
            error = 'Связь есть, УТМ недоступен'
    except ET.ParseError:
        error = 'Проблема с УТМ, проверьте Рутокен'

    return docs_in, docs_out, error


start_command_handler = CommandHandler('start', startCommand)
status_command_handler = CommandHandler('status', statusCommand)
help_command_handler = CommandHandler('help', helpCommand)
faq_command_handler = CommandHandler('faq', faqCommand)
text_message_handler = MessageHandler(Filters.text, textMessage)
filter_command_handler = CommandHandler('filter', filterCommand)

dispatcher.add_handler(start_command_handler)
dispatcher.add_handler(text_message_handler)
dispatcher.add_handler(help_command_handler)
dispatcher.add_handler(faq_command_handler)
dispatcher.add_handler(status_command_handler)
dispatcher.add_handler(filter_command_handler)

updater.start_polling(clean=True)

updater.idle()
