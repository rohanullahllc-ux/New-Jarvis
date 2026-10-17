from config import RAPIDAPI_KEY
from bs4 import BeautifulSoup
from MainCode import Speak
import requests


def BusinessNameGenerator(BusinessName):
    url = "https://business-name-generator.p.rapidapi.com/"

    querystring = {"q":BusinessName}

    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "business-name-generator.p.rapidapi.com"
    }

    response = requests.get(url, headers=headers, params=querystring)
    Data = response.json()
    for data in Data:
        l = data
        print(l)
    print("\n")
    Speak(f"Sir above are some names you can use it for your {BusinessName}")


def get_latest_crypto_price(coin):
    url = 'https://www.google.com/search?q=' + (coin) + 'price'
    HTML = requests.get(url)
    soup = BeautifulSoup(HTML.text, 'html.parser')
    texti = soup.find('div', attrs={
        'class': 'BNeawe iBp4i AP7Wnd'
    }).find({
        'div': 'BNeawe iBp4i AP7Wnd'
    }).text
    
    Speak(f"Price of {coin} is {texti}")


def CurrencyExchangeRates():
    from bs4 import BeautifulSoup
    import requests as req

    currencies = []

    page = req.get('https://www.x-rates.com/').text

    soup = BeautifulSoup(page, 'html.parser')

    options = soup.find_all('option')[:-11]

    for option in options:
        currency_short = option.text[:(option.text.find(" "))]
        currency_name = option.text[(option.text.find(" ") + 3):]
        current_element = {'name': currency_name, 'short': currency_short}
        currencies.append(current_element)
        print('{}. {} ({})'.format(len(currencies), current_element['name'],
                                current_element['short']))

    Speak("Enter your currency\'s position number...")
    currency_index = int(input('Enter your currency\'s position number: ')) - 1
    currency = currencies[currency_index]
    Speak("Enter amount (if amount isn\'t integer, then write it with a dot, not comma")
    amount = input(
        '\033cEnter amount of {}s (if amount isn\'t integer, then write it with a dot, not comma): '
        .format(currency['name'].lower()))

    currencies_table_url = 'https://www.x-rates.com/table/?from={}&amount={}'.format(
        currency['short'], amount)

    currencies_table_page = req.get(currencies_table_url).text

    soup = BeautifulSoup(currencies_table_page, 'html.parser')

    table_rows = soup.findChild('table', attrs={
        'class': 'tablesorter'
    }).findChildren('tr')[1:]

    Speak('\033cFor {} {}s you\'ll get:'.format(amount, currency['name'].lower()))

    for table_row in table_rows:
        row_data = table_row.findChildren('td')
        exchange_rate = {
            'currency': row_data[0].text,
            'amount': float(row_data[1].text)
        }
        Speak('{:.3f} {}s'.format(exchange_rate['amount'],
                              exchange_rate['currency']))

