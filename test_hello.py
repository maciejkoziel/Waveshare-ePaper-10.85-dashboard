#!/usr/bin/python3
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib/waveshare_epd'))
from epd10in85g import EPD
from PIL import Image, ImageDraw, ImageFont

FONT_DIR = os.path.join(os.path.dirname(__file__), 'fnt')

epd = EPD()
print("Init...")
epd.Init()
print("Clear...")
epd.Clear()

img = Image.new("RGB", (1360, 480), "white")
draw = ImageDraw.Draw(img)

font = ImageFont.truetype(os.path.join(FONT_DIR, 'ArchivoBlack-Regular.ttf'), 100)

draw.text((80,  180), "HELLO",  font=font, fill="black")
draw.text((80,  300), "WORLD",  font=font, fill="red")
draw.text((680, 180), "HELLO",  font=font, fill=(255, 255, 0))
draw.text((680, 300), "WORLD",  font=font, fill="black")

# color swatches in corners
draw.rectangle([(0, 0), (60, 60)],     fill="black")
draw.rectangle([(0, 420), (60, 480)],  fill="red")
draw.rectangle([(1300, 0), (1360, 60)],   fill=(255, 255, 0))

print("Displaying (~21s)...")
epd.display(epd.getbuffer(img))
print("Done.")
epd.sleep()
