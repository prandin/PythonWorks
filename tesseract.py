import fitz
import pandas as pd
import pdfplumber
import numpy as np

import openpyxl
import os
import re
import shutil
import math
import PIL

import pytesseract
import cv2
from PIL import Image

pd.set_option('display.max_colwidth', 0)
pd.set_option('mode.chained_assignment',None)
pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)

pytesseract.pytesseract.tesseract_cmd = os.path.join(os.getcwd(), 'Tesseract-OCR', 'tesseract.exe')

def pdf_to_ocr(input_file_path, output_file_path):
    
    contents = []
    f = open(input_file_path, 'rb')
    #filez = open(files, 'rb')

    docs=fitz.open(f)
    page_no=docs.page_count
    resolution_parameter = 300
    
    #for each page
    for i in range(page_no):
        page = docs.load_page(i)  # number of page

        pix = page.get_pixmap(dpi = resolution_parameter)
        file_name=file.replace('.pdf','')
        output = output_file_path +file_name+'-'+str(i)+'.jpg'
        pix.pil_save(output, optimize = False, dpi = (1500, 1500))

        #now the page is generated
        #get the text

        #img = Image.open(output)
        
        img = cv2.imread(output)
        config = ('-l eng --oem 1 --psm 6')
        data = pytesseract.image_to_string(img, config=config)

        
        if data is None:
            contents_data = ''
        else:
            contents_data = data.split('\n')
            
            contents_data = [item.upper() for item in contents_data]
            
            
            for line in contents_data:
                contents.append(line)
        df = pd.DataFrame(data = contents)
        

    #display(df)
    return df
  
  entries= os.listdir('./Input')
df = pd.DataFrame()
files=[]
contents = []
for i in entries:
    if(os.path.splitext(i)[1] == ".pdf" or os.path.splitext(i)[1] == ".PDF"):
        files.append(os.path.splitext(i)[0])
#     if os.path.splitext(i)[0] == "Scan_20220110_100818":
#         files.append(os.path.splitext(i)[0])
        
if not files:
    print("Input folder is empty or does not have pdf files")
#first, convert each page to image
os.getcwd()
path=os.getcwd()
output_file_path=path+'\\Images\\'
contents_data = ""
contents = []

for file in files:
    
    input_file_path = './Input/'+ file + ".pdf"
    
    df = pdf_to_ocr(input_file_path, output_file_path)
    df_string = str(df)
    
