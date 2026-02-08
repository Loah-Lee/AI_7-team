import os


if __name__ == '__main__':
    files = os.listdir('./data')
    for file in files:
        f_name, ext = file.split('.')
        if ext == 'hwp':
            if os.path.exists(f'output/temp_pdf/{f_name}.pdf'):
                continue
            os.system(f"python hwp_converter.py data/{file} -o output/temp_pdf")
        else:
            os.system(f"cp data/{file} output/temp_pdf/{file}")

    os.system('python parser_step1.py')
    os.system('python auditor_reader_step23.py')
    os.system('python chunker_step4.py')
    os.system('python storage_step5.py')
    