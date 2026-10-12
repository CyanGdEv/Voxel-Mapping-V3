"""Conservative ASCII coordinate-label runs bound to actual text-show operators."""
import math

STANDARD_FONTS={'Helvetica','Helvetica-Bold','Helvetica-Oblique','Helvetica-BoldOblique','Times-Roman','Times-Bold','Times-Italic','Times-BoldItalic','Courier','Courier-Bold','Courier-Oblique','Courier-BoldOblique'}


def coordinate_runs(page,*,max_fragments=2000,max_text=500000,max_operations=100000):
    """Avoid delayed text visitor origins; do not guess custom font encodings.

    Each run needs its own explicit positioning operator. PDF text advances,
    forms and quote operators are not reconstructed by this narrow adapter.
    """
    if min(max_fragments,max_text,max_operations)<1:raise ValueError('Positive coordinate text budgets required')
    content=page.get_contents()
    if content is None:return []
    if len(content.get_data())>10000000 or len(content.operations)>max_operations:raise ValueError('Coordinate text content budget exceeded')
    resources=page.get('/Resources',{})
    if hasattr(resources,'get_object'):resources=resources.get_object()
    fonts=resources.get('/Font',{})
    if hasattr(fonts,'get_object'):fonts=fonts.get_object()
    font_key=None;size=0;positioned=False;stack=[];runs=[];characters=0;fragments=0
    def before(operator,operands,cm,tm):
        nonlocal font_key,size,positioned,characters,fragments
        if operator==b'Do':raise ValueError('Form/XObject text origins require a separate adapter')
        if operator==b'Tr' and int(operands[0])>=4:raise ValueError('Clipped text coordinate origins are unsupported')
        if operator==b'Ts' and float(operands[0])!=0:raise ValueError('Raised text coordinate origins require a separate adapter')
        if operator==b'q':
            if len(stack)>=64:raise ValueError('Coordinate text stack budget exceeded')
            stack.append((font_key,size))
        elif operator==b'Q':
            if not stack:raise ValueError('Unbalanced coordinate text graphics state')
            font_key,size=stack.pop()
        elif operator==b'Tf':font_key,size=str(operands[0]),float(operands[1])
        elif operator in (b'BT',b'ET'):positioned=False
        elif operator in (b'Tm',b'Td',b'TD',b'T*'):positioned=True
        elif operator in (b"'",b'"'):positioned=False
        elif operator in (b'Tj',b'TJ'):
            fragments+=1
            if fragments>max_fragments:raise ValueError('Coordinate-label fragment budget exceeded')
            parts=[operands[0]] if operator==b'Tj' else [v for v in operands[0] if isinstance(v,(str,bytes))]
            try:text=''.join(v.decode('ascii') if isinstance(v,bytes) else str(v) for v in parts)
            except UnicodeDecodeError:text=''
            characters+=len(text)
            if characters>max_text:raise ValueError('Coordinate-label text budget exceeded')
            font=fonts.get(font_key) if font_key else None
            if hasattr(font,'get_object'):font=font.get_object()
            supported=font and str(font.get('/BaseFont','')).lstrip('/') in STANDARD_FONTS and font.get('/Subtype')=='/Type1' and font.get('/Encoding') in (None,'/WinAnsiEncoding','/MacRomanEncoding','/StandardEncoding') and not font.get('/ToUnicode')
            leading_adjustment=operator==b'TJ' and any(isinstance(v,(int,float)) and v!=0 for v in list(operands[0])[:next((i for i,v in enumerate(operands[0]) if isinstance(v,(str,bytes))),len(operands[0]))])
            if positioned and supported and not leading_adjustment and text.isascii() and text.strip():
                x=tm[4]*cm[0]+tm[5]*cm[2]+cm[4];y=tm[4]*cm[1]+tm[5]*cm[3]+cm[5]
                if not all(math.isfinite(v) for v in (x,y,size)):raise ValueError('Nonfinite coordinate text position')
                runs.append({'text':text,'origin':[x,y],'cm':list(cm),'tm':list(tm),'font':font,'size':size,'origin_basis':'explicit_positioned_text_show_operator'})
            positioned=False # No inference from another run's text advance.
    page.extract_text(visitor_operand_before=before)
    if stack:raise ValueError('Unbalanced coordinate text graphics state')
    return runs
