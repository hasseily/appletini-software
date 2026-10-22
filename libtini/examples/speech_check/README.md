# Speech check

The speech check is a text-mode check for SSI-263 speech on the slot-4
Mockingboard or Phasor. Boot `build/speech_check.po`. It runs for a maximum of
about 25 seconds, shows one line for each test and waits for a key.

```powershell
python tools/build.py --cc65-home D:/Repos/cc65 --game speech_check
```

| Line | Meaning |
| --- | --- |
| `VIA-B T2` | Whether timer 2 of the $C480 VIA counts. When it counts, the joystick reader uses it |
| `RAW START` | The SSI starts directly, without the speech code of the driver. The line gives the VIA that set the CA1 flag for a finished phoneme, and the time. `NONE` after 1.00 s means that no flag came: the SSI-263 has no clock |
| `RAW PHONEMES` | The four phonemes of READY, one at a time: the number that finished, the flags of each VIA and the total time. `0/4` means that no phoneme finished |
| `MOCKINGBOARD`, `PHASOR` | The libtini driver says READY and EXCELLENT. The line gives `OK` and the time, or the first error and its time. `SEEN` counts the finished-phoneme signals that the check read before the driver took them. In Phasor mode the interrupt handler takes them first, thus `SEEN` stays 0 |
| `MB+JOYSTICK`, `PH+JOYSTICK` | The same test with a joystick read each 30 ms. `J` gives the number of reads and of failed reads |

`TIMING AT 2.00S` on a driver line means that a phoneme did not finish within
the two-second limit of the driver. After this error, the driver refuses
speech until it starts again. When all lines fail and RAW START shows `NONE`,
the SSI-263 has no clock. In standalone ONE//e mode, speech needs Appletini
firmware F1.3.2 or later.

In the development emulator, all lines show success and `VIA-B T2 DOES NOT
COUNT`.
