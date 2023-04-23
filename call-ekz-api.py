import sys
import requests
import yaml
from datetime import datetime, timedelta

def get_data(jsession_cookie, contractId):
    yesterday = datetime.now() - timedelta(days=1)
    year, month, day = yesterday.year, yesterday.month, yesterday.day

    url = f"https://my.ekz.ch/api/cos-sc/data-views/v1/smart-meter-data/contract-load-profile?contractId={contractId}&year={year}&month={month}&day={day}"

    headers = {
        "Cookie": f"JSESSIONID={jsession_cookie}",
    }

    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error: {response.status_code}")
        return None

def print_values_as_home_assistant_yaml(data):
    consumption_data = data.get('consumptionLoadProfile')
    
    yesterday = datetime.now() - timedelta(days=1)
    year, month, day = yesterday.year, yesterday.month, yesterday.day

    values = []
    peak_energy_usage = 0
    off_peak_energy_usage = 0

    for i, item in enumerate(consumption_data):
        timestamp = datetime(year, month, day) + timedelta(minutes=i * 15) + timedelta(minutes=15)
        value = item['value'] / 4

        if yesterday.weekday() < 5 and 7 <= timestamp.hour < 20:
            peak_energy_usage += value
        else:
            off_peak_energy_usage += value

        values.append({
            'timestamp': timestamp.isoformat(),
            'value': value,
            'unit_of_measurement': 'kWh'
        })

    daily_energy_usage = sum(item['value'] for item in values)
    values.append({'daily_energy_usage': daily_energy_usage, 'unit_of_measurement': 'kWh'})
    values.append({'peak_energy_usage': peak_energy_usage, 'unit_of_measurement': 'kWh'})
    values.append({'off_peak_energy_usage': off_peak_energy_usage, 'unit_of_measurement': 'kWh'})

    peak_cost = (peak_energy_usage * 23.66) / 100
    off_peak_cost = (off_peak_energy_usage * 19.35) / 100
    total_cost = peak_cost + off_peak_cost

    values.append({'peak_cost': peak_cost, 'unit_of_measurement': 'CHF'})
    values.append({'off_peak_cost': off_peak_cost, 'unit_of_measurement': 'CHF'})
    values.append({'total_cost': total_cost, 'unit_of_measurement': 'CHF'})

    yaml_output = yaml.dump(values, default_flow_style=False)
    print(yaml_output)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python call-ekz-api.py <JSESSIONID_cookie_value>")
        sys.exit(1)

    jsession_cookie_value = sys.argv[1]
    contractId = sys.argv[2]
    data = get_data(jsession_cookie_value, contractId)

    if data:
        print_values_as_home_assistant_yaml(data)
