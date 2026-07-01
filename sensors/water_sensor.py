from m5stack import *
from m5ui import *
from uiflow import *
import wifiCfg
import machine
import ujson
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

# Connect WiFi
wifiCfg.doConnect(WIFI_SSID, WIFI_PASSWORD)
lcd.clear()
lcd.print("Connecting MQTT...", 10, 20, 0xFFFFFF)

# Connect MQTT
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

last_state = False   # False = dry, True = wet

while True:

    value = adc.read()

    if value > 2000:
        lcd.clear()
        lcd.print("WATER DETECTED", 10, 30, 0x0000FF)
        lcd.print("ADC: {}".format(value), 10, 60, 0x00FF00)

        # Publish only once when transitioning from dry to wet
        if not last_state:
            client.publish(MQTT_TOPIC, str(value).encode())
            last_state = True

    else:
        lcd.clear()
        lcd.print("DRY", 10, 30, 0xFF0000)
        lcd.print("ADC: {}".format(value), 10, 60, 0x00FF00)

        last_state = False

    wait_ms(500)