from m5stack import *
from m5ui import *
from uiflow import *
import wifiCfg
import machine
from umqtt.simple import MQTTClient

# WiFi Settings
WIFI_SSID = "quinnie"
WIFI_PASSWORD = "12345678"

# MQTT Settings
MQTT_BROKER = "192.168.137.1"
MQTT_PORT = 1883
MQTT_CLIENT_ID = "stick1"
MQTT_TOPIC = b"water/sensor1"

# Stick Screen
setScreenColor(0x111111)
lcd.clear()
lcd.print("Connecting WiFi...", 10, 20, 0xFFFFFF)

wifiCfg.doConnect(WIFI_SSID, WIFI_PASSWORD)

lcd.clear()
lcd.print("Connecting MQTT...", 10, 20, 0xFFFFFF)

client = MQTTClient(
    client_id=MQTT_CLIENT_ID,
    server=MQTT_BROKER,
    port=MQTT_PORT
)

client.connect()

lcd.clear()
lcd.print("MQTT Connected!", 10, 20, 0x00FF00)

# Water Sensor
adc = machine.ADC(machine.Pin(36))
adc.atten(machine.ADC.ATTN_11DB)

last_state = False   # False = dry, True = wet

while True:

    value = adc.read()

    lcd.clear()

    # ADC value at the top
    lcd.print("ADC:", 10, 10, 0xFFFFFF)
    lcd.print(str(value), 55, 10, 0x00FF00)

    if value > 2000:
        # line gap before status
        lcd.print("WATER", 10, 50, 0x0000FF)
        lcd.print("DETECTED", 10, 75, 0x0000FF)

        if not last_state:
            client.publish(MQTT_TOPIC, str(value).encode())
            last_state = True

    else:
        lcd.print("DRY", 10, 55, 0xFF0000)

        if last_state:
            client.publish(MQTT_TOPIC, b"0")
            last_state = False

    wait_ms(500)