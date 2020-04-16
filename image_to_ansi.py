from PIL import Image
import sys
import math

def scale_img(img, scale):
    return img.resize((math.ceil(img.size[0] * scale), math.ceil(img.size[1] * scale)))

def convert_to_ansi(img):
    text = ''
    last_color = None
    ansi_color = lambda color: f'\033[48;2;{color[0]};{color[1]};{color[2]}m'
    for y in range(img.size[1]):
        for x in range(img.size[0]):
            color = img.getpixel((x, y))
            if color != last_color:
                text += ansi_color(color)
                last_color = color
            text += ' '
        text += '\033[0m\n'
        last_color = None
    return text

def image_to_ansi(img, char_limit):
    img = img.convert('RGB')
    top_scale = 1
    bottom_scale = 0
    best_scale = None
    prev_scale = None
    img = img.resize((img.size[0], math.ceil(img.size[1] / 2)))
    while True:
        scale = (top_scale + bottom_scale) / 2
        scaled_img = scale_img(img, scale)
        ansi = convert_to_ansi(scaled_img)
        chars_over = len(ansi) - char_limit
        if prev_scale == scale:
            break
        if chars_over > 0:
            top_scale = scale
        elif chars_over < 0:
            bottom_scale = scale
            best_scale = scale
        else:
            break
        prev_scale = scale    

    scaled_img = scale_img(img, best_scale)
    ansi = convert_to_ansi(scaled_img)
    return ansi



