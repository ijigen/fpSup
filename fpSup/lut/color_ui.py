"""LUT's FT4S file: the manager (manager_page.py, v4 SupManager's page as
RES-Custom's) and a cube's settings (settings_y51.py: Y5_1's own popup lists), one
state machine.  The fpSup row opens the manager by the firmware's transition;
AEL there opens the settings by LC_Go's change event; MENU goes back.
"""
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'uishare/tab'))
import build_fp4 as F
import home4_page as H
import manage_page as M
import ft6_page as P
import settings_page as S
import settings_y51 as Y
import manager_page as MP

MACHINE='TransColor'
PREFIX='LC_'
AEL_HINT='<!font_G_bt_AEL_K153,CENTER>Further Options'      # the stock Footer14_R


def make_page(title_text='LUT settings',settings=True):
    """The settings page (settings=True); the slot form is no longer used."""
    img,pool=P.stock_pool()
    pg=M.Management(img,pool)
    M.manager_header(pg,title_text,head_var=H.HEAD_VAR)
    title_record=next(r for r in pg.seq if len(r)>36 and P.pool_name(pg,r)=='drawText'
                      and pool.text(P.u32(r,32))==title_text)
    prior={id(r) for r in pg.seq}
    pg.bind(pg.seq,P.u32(title_record,20),'FT_PageTitle',P.u32(title_record,24),'text')
    pg.added += [r for r in pg.seq if id(r) not in prior]
    out,m=M.jump_row(pg,0,' ',focus=M.FOCUS)
    title=out[P.comp(out,P.by_object(out)[m[P.KEEP_ROW]],'objectBase',pool)]
    for prop in ('opacity','is-visible'):
        pg.bind(out,m[P.KEEP_ROW],H.TITLE_VAR,P.u32(title,24),prop,1)
    M.page_tabs(pg,out,m[P.ROW_ITEM])
    for old in (10062,3457):
        r=out[P.comp(out,P.by_object(out)[m[old]],'drawImage',pool)]
        P.put(r,32,pool.find('blank'))
    M.move_hidden(out[P.comp(out,P.by_object(out)[m[3456]],'objectBase',pool)])
    pg.append_action(out,m[P.ROW_ITEM],'focusEvent','FocusOn',
                     lambda ev,order:pg.write(m[P.ROW_ITEM],ev,order,M.PAGE_KEY,31))
    for key,code in (('Left',M.PREVIOUS),('Right',M.NEXT)):
        pg.event(out,m[P.ROW_ITEM],key,lambda ev,code=code:[pg.write(m[P.ROW_ITEM],ev,1,M.PAGE_KEY,code)])
    pg.add(out)
    row0=0
    if settings:                       # Color space / Gamma: stock scrolling lists
        for k,spec in enumerate((S.SPACE,S.GAMMA)):
            out,rm=S.foreign_row(pg,k,spec);pg.add(out)
            row0=row0 or rm[S.DONOR_SELECT]
    else:
        raise ValueError('the manager is manager_page.build()')
    pg.root_focus(M.FOCUS)
    M.enter_write(pg,M.GO_VAR,0)      # entered from the fpSup row's request: the core forgets the name
    if settings:M.enter_write(pg,MP.GO_VAR,0)     # ... and from the manager's
    M.chrome(pg,manage=True);M.colour_clips(pg)
    # Every MENU exit on this private page asks its own machine for Return.
    for i,r in list(enumerate(pg.seq)):
        if len(r)<12 or P.u32(r,0)!=0x10006 or P.pool_name(pg,r)!='keyEvent' or pool.text(P.u32(r,20))!='Menu':
            continue
        for action in pg.seq[i+1:i+1+P.u32(r,16)]:
            if P.pool_name(pg,action)=='controlAppState' and len(action)!=41:
                request=bytearray(pg.raw[P.row_actions_raw(pg,P.ROW_ITEM,'Right')])
                for off in (20,24,28):P.put(request,off,P.u32(action,off))
                pg.request(request,'Return');action[:]=request
    # Notify our controller before the native Return transition, so the
    # parent's values are ready when the shared LC_ widgets appear there.
    i=0
    while i<len(pg.seq):
        r=pg.seq[i]
        if len(r)>=12 and P.u32(r,0)==0x10006 and P.pool_name(pg,r)=='keyEvent' and pool.text(P.u32(r,20))=='Menu':
            count=P.u32(r,16)
            for j in range(i+1,i+1+count):
                action=pg.seq[j]
                if P.pool_name(pg,action)=='controlAppState':
                    P.put(action,28,2)
                    notice=pg.write(P.u32(action,20),P.u32(action,24),1,'FT_Key',70)
                    pg.seq.insert(j,notice);pg.added.append(notice)
                    P.put(r,16,count+1);break
            i+=P.u32(r,16)
        i+=1
    if settings:                       # its lists bring component kinds MainY5 lacks
        import build_menu_candidate as BM
        stock=BM.extend_header;BM.extend_header=S.extend_header_with_kinds(pool)
        try:page,refs=pg.finish()
        finally:BM.extend_header=stock
    else:page,refs=pg.finish()
    names={n for _ty,n,_first in F.home_vars(row0)}|{'FT_PageTitle','FT_RightFooter'}
    refs=[(o,PREFIX+t[3:] if t in names else t) for o,t in refs]
    return page,refs,row0


def make_settings(title_text='LUT settings'):
    """The settings page on Y5_1 (settings_y51.py), its FT_ names as this sup's LC_ ones."""
    page,refs,row0=Y.build(title_text)
    names={n for _ty,n,_first in F.home_vars(row0)}|{'FT_PageTitle','FT_RightFooter'}
    return page,[(o,PREFIX+t[3:] if t in names else t) for o,t in refs],row0


SETTINGS_PAGE='FT_LUTSET'
SETTINGS_VARS=[(F.VAR_INT,v,0) for v in ('LC_SpaceV','SUB_LC_SpaceV','LC_Back','LC_GammaV','SUB_LC_GammaV',
                                       'LC_GammaX',S.ZERO)]+[(F.VAR_INT,'LC_GammaM',5),
               (F.VAR_TEXT,'LC_SpaceT',' '),(F.VAR_TEXT,'LC_GammaT',' ')]
# native/color_ui.c MV_MATRIX_*: the third settings row (after MV_GO)
MATRIX_VARS=[(F.VAR_INT,'LC_MatrixV',0),(F.VAR_INT,'LC_MatrixX',0),(F.VAR_INT,'LC_MatrixM',1),
             (F.VAR_TEXT,'LC_MatrixT',' ')]
# conv.c: the converting overlay's opacity and the hourglass frames' (MV_BUSY, MV_CLOCK0..2)
BUSY_VARS=[(F.VAR_INT,MP.BUSY_VAR,0)]+[(F.VAR_INT,f'{MP.CLOCK_VAR}{k}',0) for k in range(3)]
# conv.c conv_chart: the ColorChecker (MV_CHART, MV_BAR, MV_MATCH, MV_PATCH0..+47; manager_page.checker_chart)
CHART_VARS=MP.chart_vars()
# the settings page's "Color chart" row (settings_y51.CHART): its value text (color_ui.c MV_CHART_T)
CHART_ROW_VARS=[(F.VAR_TEXT,'LC_ChartT',' ')]
# native/color_ui.c T_*: the manager's footer texts are SupManager's (fixed, as RES-Custom's)
TEXTS=(' ',F.SUPMGR_TEXTS[5],F.SUPMGR_TEXTS[6],F.SUPMGR_TEXTS[7],'List full: disable one','Write failed',
       'Recording busy','No LUT files',MP.PAGE,AEL_HINT,'Set up first: AEL',MP.GO_TEXT,'LUT (',Y.BACK_TEXT,
       'Convert again',                 # T_AGAIN: the chart row, a .JFT without its chart block (or none)
       'COLOR list needs COL-Share',    # T_NOCOLS: no COL-Share on the card -> no COLOR rows (Bei 2026-11-07 #2)
       'No COLOR row: list full')       # T_NOROW: on, but the COLOR list has no row left for it (Bei 2026-11-10)
TRANSITIONS=((MP.PAGE,F.HOME_PAGE,'Return'),(SETTINGS_PAGE,MP.PAGE,'Return'),
             (MP.PAGE,SETTINGS_PAGE,SETTINGS_PAGE))+F.open_transitions(MP.PAGE)


def variables(row0=0,srow0=0,slots=()):
    """color_ui.c MV_*: the manager's (supmgr.c order, LC_), then the settings page's."""
    return MP.manager_vars(row0)+[(F.VAR_TEXT,'LC_PageTitle',' '),(F.VAR_INT,'LC_SRow0',srow0)]+SETTINGS_VARS+[
        (F.VAR_INT,f'LC_RowId{k}',slots[k] if k<len(slots) else 0) for k in range(6)]+[(F.VAR_INT,MP.GO_VAR,0)]+MATRIX_VARS+BUSY_VARS+CHART_VARS+CHART_ROW_VARS


def data_file():
    page,refs,row0,slots=MP.build()
    spage,srefs,srow0=make_settings('LUT settings')
    declared={n for _t,n,_v in variables()}
    for _o,t in refs+srefs:
        if t.startswith('LC_') and t not in {MP.GO_TEXT,MP.CONV_EVENT,MP.BUSY_EVENT,Y.BACK_TEXT,*(n for n,_ in Y.models())} and t not in declared:   # requests / list models / the app state are no variables
            raise ValueError(f'a page names {t}, which is not declared')
    return F.ft4_file([(MP.PAGE,(page,refs)),(SETTINGS_PAGE,(spage,srefs))],TRANSITIONS,MACHINE,
                      variables(row0,srow0,slots),TEXTS,S.csv_pack(Y.models()))
