'''To be copied and pasted into the M5Stack UIFlow IDE'''

from m5stack import *
from m5ui import *
from uiflow import *
import wifiCfg
import machine
import time
from umqtt.simple import MQTTClient


# =========================
# WiFi Settings
# =========================

WIFI_SSID = "quinnie"
WIFI_PASSWORD = "12345678"


# =========================
# MQTT Settings
# =========================

MQTT_BROKER = "192.168.137.1"
MQTT_PORT = 1883

# Must be different from the water sensor's client ID
MQTT_CLIENT_ID = "stick_touch"
MQTT_TOPIC = b"sensors/button"


# =========================
# Touch Sensor Settings
# =========================

# Green wire connected to GPIO32
TOUCH_PIN = 32

# Built-in LED
LED_PIN = 10

# Lower value means less sensitive
# Try between 0.60 and 0.80
TOUCH_RATIO = 0.70


# =========================
# Screen Setup
# =========================

lcd.setRotation(3)
setScreenColor(0x111111)

lcd.clear()
lcd.print("Connecting WiFi...", 10, 20, 0xFFFFFF)


# =========================
# Connect to WiFi
# =========================

wifiCfg.doConnect(WIFI_SSID, WIFI_PASSWORD)

lcd.clear()
lcd.print("Connecting MQTT...", 10, 20, 0xFFFFFF)


# =========================
# Connect to MQTT
# =========================

client = MQTTClient(
    client_id=MQTT_CLIENT_ID,
    server=MQTT_BROKER,
    port=MQTT_PORT,
    keepalive=60
)

client.connect()

lcd.clear()
lcd.print("MQTT Connected!", 10, 20, 0x00FF00)
wait_ms(1000)


# =========================
# Touch Sensor Setup
# =========================

touch_sensor = machine.TouchPad(machine.Pin(TOUCH_PIN))

# Built-in LED is active-low
led = machine.Pin(LED_PIN, machine.Pin.OUT)
led.value(1)


# =========================
# Calibration
# =========================

lcd.clear()
lcd.print("CALIBRATING...", 10, 20, 0xFFFFFF)
lcd.print("Do not touch wire", 10, 50, 0xFFFF00)

total = 0
samples = 40

for i in range(samples):
    total += touch_sensor.read()
    wait_ms(25)

baseline = total // samples

touch_threshold = int(baseline * TOUCH_RATIO)
release_threshold = int(baseline * 0.85)

print("Baseline:", baseline)
print("Touch threshold:", touch_threshold)
print("Release threshold:", release_threshold)

lcd.clear()
lcd.print("NO TOUCH", 10, 35, 0xFFFFFF)


# False = not touched
# True = touched
touching = False
last_state = False

last_ping = time.ticks_ms()


# =========================
# Main Loop
# =========================

while True:

    reading = touch_sensor.read()

    # Touch values normally decrease when touched
    if not touching and reading < touch_threshold:
        touching = True

    elif touching and reading > release_threshold:
        touching = False


    # Only update and publish when state changes
    if touching != last_state:

        lcd.clear()

        if touching:

            lcd.print("TOUCH DETECTED", 10, 35, 0x00FF00)
            lcd.print("MQTT: 1", 10, 65, 0xFFFFFF)

            client.publish(MQTT_TOPIC, b"1")

            print("Published: sensors/button = 1")

        else:

            lcd.print("NO TOUCH", 10, 35, 0xFFFFFF)
            lcd.print("MQTT: 0", 10, 65, 0xFFFFFF)

            client.publish(MQTT_TOPIC, b"0")

            led.value(1)

            print("Published: sensors/button = 0")

        last_state = touching


    # Blink built-in LED while touched
    if touching:

        led.value(0)
        wait_ms(100)

        led.value(1)
        wait_ms(100)

    else:

        wait_ms(30)


    # Keep MQTT connection alive
    if time.ticks_diff(time.ticks_ms(), last_ping) > 30000:

        try:
            client.ping()
        except:
            try:
                client.connect()
            except:
                pass

        last_ping = time.ticks_ms()