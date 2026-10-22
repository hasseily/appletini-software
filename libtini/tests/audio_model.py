"""Independent VIA/AY/SSI register fixture for actual linked driver tests.

Device microseconds advance from CPU cycles divided by a selectable factor.
This checks cadence logic, not Appletini bus timing or speech synthesis.
"""
from apple2_model import Apple2Memory

class AudioMemory(Apple2Memory):
    def __init__(self,speed=1,present=True,speech=True,t2=True):
        super().__init__(4)
        self.speed=speed;self.present=present;self.speech=speech;self.t2=t2
        self.regs=bytearray(256);self.ier=0;self.ifr=0
        self.timer_next=None;self.t2_start=0;self.ssi_next=None;self.ssi_d7=False
        self.timer_start=None;self.timer_stop=None
        self.enabled_periods=0
        self.ssi_control=128;self.ssi_latched=0xC0;self.native=False
        self.ay=[bytearray(16) for _ in range(4)]
        self.ay_latch=[0]*4;self.ora=[0,0];self.ssi_writes=[];self.ay_writes=[]
        self.keyboard_inject=False;self.paddle_start=[0,0];self.paddle_open=0;self.paddle_value=[0,0];self.paddle_strobes=0
        self.key_phase=0;self.key_strobe=False
        self.native_supported=True
        self.audio_reads=0
    def now(self):return self.cpu.processorCycles//self.speed if self.cpu else 0
    def update(self):
        now=self.now()
        if self.timer_next is not None and now>=self.timer_next:
            periods=(now-self.timer_next)//10000+1
            if self.ier&64:self.enabled_periods+=periods
            self.ifr|=64
            self.timer_next+=periods*10000
        if self.ssi_next is not None and now>=self.ssi_next:
            self.ssi_d7=True;self.ssi_next=None
            if not self.native:self.regs[0x1D]|=2
    def pending(self):
        self.update()
        return bool(self.ifr&self.ier or self.native and self.ssi_d7)
    def __getitem__(self,address):
        if isinstance(address,int) and 0xC400<=address<=0xC4FF:return self.read_audio(address)
        return super().__getitem__(address)
    def __setitem__(self,address,value):
        if isinstance(address,int) and 0xC400<=address<=0xC4FF:self.write_audio(address,value);return
        super().__setitem__(address,value)
    def read_audio(self,address):
        self.audio_reads+=1
        if not self.present:return 0
        self.update();offset=address&255
        if offset==0x8E:return self.ier|128
        if offset==0x1E:return 128
        if offset==0x8D:return self.ifr|(128 if self.ifr&self.ier else 0)
        if offset==0x84:self.ifr&=~64;return 0
        if offset==0x85 and self.timer_next is not None:
            # T1 free-runs L..0, $FFFF, then reloads L, every 10000 device clocks.
            value=(self.timer_next-self.now()-1)%10000-1
            return (value&65535)>>8
        if offset in (0x88,0x89):
            if not self.t2:return 255  # a VIA model without a counting T2
            value=(65535-(self.now()-self.t2_start))&65535
            return value&255 if offset==0x88 else value>>8
        if offset==0x40 and self.native:return 128 if self.ssi_d7 else 0
        if offset in (0x11,0x1F) and self.regs[0x13]==0 and self.regs[0x10]&3==1:
            chip=1 if self.native and self.regs[0x10]&8==0 else 0
            return self.ay[chip][self.ay_latch[chip]]
        return self.regs[offset]
    def write_audio(self,address,value):
        if not self.present:return
        self.update();offset=address&255;value&=255
        self.regs[offset]=value
        if offset==0x8E:
            previous_ier=self.ier
            self.ier=(self.ier|value&127) if value&128 else self.ier&~value
            if value==64 and previous_ier&64:self.timer_stop=self.now()
        elif offset==0x8D:self.ifr&=~value
        elif offset==0x1D:self.regs[offset]&=~value
        elif offset==0x85:
            if self.timer_start is None:self.timer_start=self.now()
            self.timer_next=self.now()+10000;self.ifr&=~64
        elif offset==0x89:self.t2_start=self.now()
        if 0x40<=offset<=0x44:
            self.ssi_writes.append((self.now(),offset-0x40,value))
            if offset<=0x42:self.ssi_d7=False
            if offset==0x40:
                self.ssi_latched=value
                if self.speech and not self.ssi_control&128:self.ssi_next=self.now()+30000
            if offset==0x43:
                previous=self.ssi_control;self.ssi_control=value
                if value&128:self.ssi_next=None;self.ssi_d7=False
                elif previous&128 and self.speech:self.ssi_next=self.now()+30000
            if not self.native:self.write_audio(0xC410+(offset-0x40),value)
        for via,base in enumerate((0x10,0x80)):
            if offset==base+15:self.ora[via]=value
            if offset==base:
                chips=[via*2+(1 if self.native and value&8==0 else 0)]
                for chip in chips:
                    if not value&4:self.ay[chip][:]=bytes(16)
                    elif value&3==3:self.ay_latch[chip]=self.ora[via]&15
                    elif value&3==2:
                        reg=self.ay_latch[chip];self.ay[chip][reg]=self.ora[via]
                        self.ay_writes.append((self.now(),chip,reg,self.ora[via]))
    def paddle_running(self,axis):
        # An open paddle input never finishes, like an absent stick axis:
        # 1 opens y, 2 both. A set value times like a2vm, 4+11*value clocks.
        if self.paddle_open==2 or (axis==1 and self.paddle_open==1):return True
        value=self.paddle_value[axis]
        return self.now()-self.paddle_start[axis]<(4+11*value if value else (600,1700)[axis])
    def paddle_strobe(self):
        # Any //e access to $C070-$C07F strobes the paddle timers. As on a
        # 558, a timer still running ignores the strobe.
        self.paddle_strobes+=1
        for axis in (0,1):
            if not self.paddle_running(axis):self.paddle_start[axis]=self.now()
    def _write_io(self,address,value):
        if 0xC070<=address<=0xC07F:self.paddle_strobe()
        super()._write_io(address,value)
    def _read_io(self,address):
        if address==0xC0C8:self.native=False
        if address==0xC0C5 and self.native_supported:self.native=True
        if self.key_phase:
            # Held keys: 1 D held, 2 S pending, 3 W arriving between the
            # $C000 and $C010 reads, 4 every key up. $C010 reads clear the
            # strobe and return any-key-down with the latch.
            if address==0xC000:
                return {1:0x44,2:0xD3 if self.key_strobe else 0x53,3:0x44,4:0x57}[self.key_phase]
            if address==0xC010:
                self.key_strobe=False
                return {1:0xC4,2:0xD3,3:0xD7,4:0x57}[self.key_phase]
        if address==0xC000 and self.keyboard_inject:return 0xC1
        if address in (0xC061,0xC063):return 128
        if address==0xC062:return 0
        if 0xC070<=address<=0xC07F:self.paddle_strobe()
        if address in (0xC064,0xC065):return 128 if self.paddle_running(address-0xC064) else 0
        return super()._read_io(address)
