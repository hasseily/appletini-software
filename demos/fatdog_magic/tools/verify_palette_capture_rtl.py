"""Replay assembled-loader bus traces through the unchanged capture/window RTL.

Run verify_palette_upload.py first. Its trace contains actual 6502 writes
and explicit modeled CPU acknowledgements. This test checks those writes
against real LINTXT registers and apple_cycle_capture, not the Python filter.
The firmware's existing FIFO simulation model replaces only the Xilinx FIFO.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess

DEMO = Path(__file__).resolve().parents[1]

BODY = r'''
    import apple_cycle_capture_pkg::*;
    AppleCycleRecord captured;
    logic cap_empty;
    logic cap_rd = 0;
    logic drop_unused, overlay_drop_unused, shr_unused;
    int file_handle, result, a, b, expected, records, writes;
    string kind;
    apple_cycle_capture cap (
        .clk(clk), .resetn(rstn), .soft_reset(1'b0), .ab_read(ab_read), .sss(sss),
        .line_in_frame(9'd0), .cycle_in_line(7'd0), .frame_en(1'b0),
        .fake_shr_allowed(1'b1), .overlay_devsel_enabled(devsel_enabled),
        .overlay_capture_armed(capture_armed),
        .overlay_capture_bank_aux(capture_bank_aux),
        .overlay_capture_base(capture_base), .overlay_capture_limit(capture_limit),
        .cycle_capture_data(captured), .cycle_capture_rd_en(cap_rd),
        .cycle_capture_empty(cap_empty), .capture_drop_sticky(drop_unused),
        .capture_drop_ack(1'b0), .overlay_capture_drop_sticky(overlay_drop_unused),
        .shr_capture_active(shr_unused)
    );

    task automatic check_capture(input int want);
        int count;
        count = 0;
        repeat (4) @(negedge clk);
        while (!cap_empty) begin
            if (want >= 0 &&
                (!captured.addr_decode_en || captured.addr_decode !== a[23:0] ||
                 captured.data !== b[7:0]))
                $fatal(1, "capture data mismatch addr=%06x data=%02x", a, b);
            count++;
            cap_rd = 1;
            @(negedge clk);
            cap_rd = 0;
            repeat (2) @(negedge clk);
        end
        if (want >= 0 && count != want)
            $fatal(1, "capture count at %06x: got %0d expected %0d", a, count, want);
        records += count;
    endtask

    initial begin
        ab_read = '0;
        sss = '0;
        ab_read.res = 1;
        ab_read.rw = 1;
        ab_read.cycle_valid = 1;
        repeat (4) @(negedge clk);
        rstn = 1;
        repeat (3) @(negedge clk);
        file_handle = $fopen("loader.trace", "r");
        if (!file_handle) $fatal(1, "missing loader.trace");
        records = 0;
        writes = 0;
        while (!$feof(file_handle)) begin
            result = $fscanf(file_handle, "%s %h %h %h\n", kind, a, b, expected);
            if (result != 4) $fatal(1, "invalid trace record");
            if (kind == "W") begin
                sss.addr_decode_late = a;
                sss.addr_decode_late_en = 1;
                bus_write(a[15:0], b[7:0]);
                check_capture(expected);
                writes++;
            end else if (kind == "I") begin
                sss.addr_decode_late_en = 0;
                if (a == 16'hC0F3 && b != 0 && b != 1)
                    $fatal(1, "loader issued SHOW/HIDE");
                bus_write(a[15:0], b[7:0]);
                check_capture(-1); // C029 is a separate I/O record
            end else if (kind == "A") begin
                ps_write(8'h28, a); // CPU1 ARM or CPU0 frame acknowledgement
            end else if (kind == "R") begin
                bus_read(16'hC0F4);
                if (rd !== a[7:0])
                    $fatal(1, "status mismatch got=%02x expected=%02x", rd, a);
            end else $fatal(1, "unknown trace event");
        end
        $fclose(file_handle);
        if (capture_armed || drop_unused || overlay_drop_unused)
            $fatal(1, "capture left armed or lost bytes");
        expect_status(8'hF3, 8'h00, "finished hidden and disarmed");
        $display("PALETTE LOADER RTL PASS: %0d RAM writes, %0d capture records", writes, records);
        $finish;
    end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware-root', type=Path, required=True)
    parser.add_argument('--traces', type=Path, default=DEMO / 'validation/palette-upload')
    args = parser.parse_args()
    firmware = args.firmware_root.resolve()
    output = args.traces.resolve() / 'rtl'
    output.mkdir(parents=True, exist_ok=True)
    original = (firmware / 'hdl/sim/tb_linear_text_overlay.sv').read_text()
    bench = original.split('    initial begin\n')[0] + BODY
    (output / 'tb_palette_loader.sv').write_text(bench.replace('module tb_linear_text_overlay;', 'module tb_palette_loader;'))

    def run(tool, *argv):
        executable = shutil.which(tool + '.bat') or shutil.which(tool)
        completed = subprocess.run([executable, *map(str, argv)], cwd=output,
                                   capture_output=True, text=True)
        (output / (tool + '.log')).write_text(completed.stdout + completed.stderr)
        assert completed.returncode == 0, completed.stdout[-4000:] + completed.stderr[-1000:]
        return completed.stdout

    sources = ['hdl/globals.sv', 'hdl/apple/apple_cycle_capture_pkg.sv',
               'hdl/sim/xpm_fifo_sync_model.sv', 'hdl/apple/apple_cycle_capture.sv',
               'hdl/apple/linear_text_overlay_card.sv']
    run('xvlog', '--sv', *[firmware / p for p in sources], output / 'tb_palette_loader.sv')
    run('xelab', 'tb_palette_loader', '-s', 'palette_loader_snap', '--timescale', '1ns/1ps', '-L', 'unisims_ver')
    cases = []
    for trace in sorted(args.traces.resolve().glob('*.trace')):
        shutil.copyfile(trace, output / 'loader.trace')
        log = run('xsim', 'palette_loader_snap', '--runall')
        assert 'PALETTE LOADER RTL PASS' in log and 'FAIL' not in log, log[-4000:]
        (output / (trace.stem + '.log')).write_text(log)
        cases.append({'trace': trace.name, 'sha256': hashlib.sha256(trace.read_bytes()).hexdigest()})
        print('PASS actual RTL:', trace.name, flush=True)
    assert cases
    (output / 'report.json').write_text(json.dumps({'result': 'PASS', 'cases': cases,
        'firmware_sources': {p: hashlib.sha256((firmware / p).read_bytes()).hexdigest() for p in sources},
        'physical_hardware_tested': False, 'firmware_modified': False}, indent=2) + '\n')


if __name__ == '__main__':
    main()
