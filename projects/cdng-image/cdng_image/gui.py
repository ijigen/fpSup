import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .packer import pack


class Application:
    def __init__(self, root):
        self.root=root;self.events=queue.Queue();self.cancel=threading.Event();self.running=False
        self.last_output=None
        root.title('CDNG Image · 無損素材映像檔');root.geometry('800x610');root.minsize(760,590)
        self.source=tk.StringVar();self.output=tk.StringVar()
        self.method=tk.StringVar(value='無損壓縮（Resolve）')
        self.effort=tk.StringVar(value='平衡');self.workers=tk.StringVar(value='2');self.verify=tk.BooleanVar(value=True)
        self.backend=tk.StringVar(value='Metal（Apple GPU＋CPU）' if sys.platform=='darwin' else 'CPU')
        panel=ttk.Frame(root,padding=26);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='把 RAW 素材收進一個映像檔',font=('',22,'bold')).grid(row=0,column=0,columnspan=3,sticky='w')
        ttk.Label(panel,text='逐幀無損壓縮並直接打包。完成後雙擊 ISO 掛載，即可匯入 Resolve。').grid(row=1,column=0,columnspan=3,sticky='w',pady=(8,22))
        self.controls=[]
        for row,title,var,action in [(2,'素材資料夾',self.source,self.choose_source),(3,'儲存映像檔',self.output,self.choose_output)]:
            ttk.Label(panel,text=title).grid(row=row,column=0,sticky='w',padx=(0,12),pady=8)
            entry=ttk.Entry(panel,textvariable=var);entry.grid(row=row,column=1,sticky='ew')
            button=ttk.Button(panel,text='選擇…',command=action);button.grid(row=row,column=2,padx=(10,0))
            self.controls.extend([entry,button])
        settings=ttk.Frame(panel);settings.grid(row=4,column=0,columnspan=3,sticky='ew',pady=(18,12))
        for col,title,var,values,width in [(0,'儲存方式',self.method,['無損壓縮（Resolve）','原檔打包'],24),(1,'壓縮程度',self.effort,['快速','平衡','最小體積'],14),(2,'同時處理',self.workers,['1','2','4','8'],9)]:
            block=ttk.Frame(settings);block.grid(row=0,column=col,padx=(0,22),sticky='w')
            ttk.Label(block,text=title).pack(anchor='w',pady=(0,5))
            box=ttk.Combobox(block,textvariable=var,values=values,state='readonly',width=width);box.pack()
            self.controls.append(box)
        hardware=ttk.Frame(panel);hardware.grid(row=5,column=0,columnspan=3,sticky='w',pady=(0,14))
        ttk.Label(hardware,text='運算方式').pack(side='left',padx=(0,14))
        box=ttk.Combobox(hardware,textvariable=self.backend,values=['Metal（Apple GPU＋CPU）','CUDA（NVIDIA GPU＋CPU）','CPU'],state='readonly',width=29)
        box.pack(side='left');self.controls.append(box)
        check=ttk.Checkbutton(panel,text='完成後核對映像檔內的所有檔案（RAW 像素一律逐幀驗證）',variable=self.verify)
        check.grid(row=6,column=0,columnspan=3,sticky='w',pady=(0,10));self.controls.append(check)
        ttk.Label(panel,text='保留資料夾與音訊。三種壓縮程度皆無損。\nGPU 加速預測搜尋；編碼由 CPU 完成。快速模式使用固定預測。',foreground='#666666').grid(row=7,column=0,columnspan=3,sticky='w')
        self.bar=ttk.Progressbar(panel,mode='determinate');self.bar.grid(row=8,column=0,columnspan=3,sticky='ew',pady=(22,8))
        self.status=ttk.Label(panel,text='選擇素材資料夾與儲存位置即可開始。',wraplength=710)
        self.status.grid(row=9,column=0,columnspan=3,sticky='w')
        buttons=ttk.Frame(panel);buttons.grid(row=10,column=0,columnspan=3,sticky='e',pady=(20,0))
        self.mount=ttk.Button(buttons,text='掛載映像檔',command=self.open_image,state='disabled');self.mount.pack(side='left',padx=7)
        self.stop=ttk.Button(buttons,text='取消',command=self.cancel.set,state='disabled');self.stop.pack(side='left',padx=7)
        self.start=ttk.Button(buttons,text='開始打包',command=self.begin);self.start.pack(side='left',padx=7)
        panel.columnconfigure(1,weight=1)
        root.protocol('WM_DELETE_WINDOW',self.close);root.after(100,self.poll)

    def choose_source(self):
        p=filedialog.askdirectory(title='選擇 CinemaDNG 素材資料夾')
        if p:
            self.source.set(p)
            if not self.output.get():self.output.set(str(Path(p).with_suffix('.iso')))

    def choose_output(self):
        p=filedialog.asksaveasfilename(title='儲存 ISO 映像檔',defaultextension='.iso',filetypes=[('ISO 映像檔','*.iso')])
        if p:self.output.set(p)

    def begin(self):
        if self.running:return
        source=self.source.get();output=self.output.get()
        if not source or not output:
            messagebox.showerror('缺少位置','請先選擇素材資料夾與映像檔儲存位置。');return
        self.cancel.clear();self.running=True;self.start['state']='disabled';self.stop['state']='normal';self.mount['state']='disabled'
        for c in self.controls:c['state']='disabled'
        self.bar['value']=0;self.status['text']='正在檢查素材…'
        effort={'快速':'fast','平衡':'balanced','最小體積':'max'}[self.effort.get()]
        method='store' if self.method.get()=='原檔打包' else 'lossless'
        workers=int(self.workers.get());verify=self.verify.get()
        backend={'Metal（Apple GPU＋CPU）':'metal','CUDA（NVIDIA GPU＋CPU）':'cuda','CPU':'cpu'}[self.backend.get()]
        def work():
            try:
                result=pack(source,output,effort,workers,method,verify,self.cancel,self.events.put,backend)
                self.events.put(dict(stage='finished',result=result))
            except BaseException as e:self.events.put(dict(stage='error',error=str(e),cancelled=isinstance(e,InterruptedError)))
        threading.Thread(target=work,daemon=True).start()

    def poll(self):
        try:
            while True:
                e=self.events.get_nowait();stage=e['stage']
                if stage in ('compress','verify'):
                    self.bar['value']=100*e['done']/e['total']
                    self.status['text']=('核對映像檔' if stage=='verify' else '壓縮與打包')+f" {e['done']} / {e['total']}  ·  {e['name']}"
                elif stage in ('finished','error'):
                    self.running=False;self.start['state']='normal';self.stop['state']='disabled'
                    for c in self.controls:c['state']='readonly' if isinstance(c,ttk.Combobox) else 'normal'
                    if stage=='finished':
                        r=e['result'];self.last_output=r['output'];self.mount['state']='normal';self.bar['value']=100
                        saved=r['source_bytes']-r['image_bytes']
                        change=f"節省 {r['saved_fraction']:.1%}" if saved>=0 else f"映像檔額外使用 {-saved/1024:.0f} KB"
                        self.status['text']=f"完成 · {r['files']} 個檔案 · {change} · {r['seconds']:.1f} 秒\n{r['output']}"
                    elif e['cancelled']:self.status['text']='已取消，未完成的映像檔已清除。'
                    else:
                        self.status['text']='未完成：'+e['error'];messagebox.showerror('無法完成打包',e['error'])
        except queue.Empty:pass
        self.root.after(100,self.poll)

    def open_image(self):
        if not self.last_output:return
        if sys.platform=='darwin':subprocess.Popen(['open',self.last_output])
        elif os.name=='nt':os.startfile(self.last_output)
        else:subprocess.Popen(['xdg-open',self.last_output])

    def close(self):
        if self.running:
            self.cancel.set();self.status['text']='正在取消，完成目前處理後即可關閉。'
        else:self.root.destroy()


def main():
    root=tk.Tk();Application(root);root.mainloop()
