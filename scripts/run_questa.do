if {[file exists build]} {
    file delete -force build
}
file mkdir build
cd build

if {[file exists work]} {
    vdel -lib work -all
}
vlib work
vmap work work

vlog -sv \
    +incdir+../tb \
    ../rtl/timebase_gen.v \
    ../rtl/button_conditioner.v \
    ../rtl/watchdog_core.v \
    ../rtl/regfile.v \
    ../rtl/uart_rx.v \
    ../rtl/uart_tx.v \
    ../rtl/uart_protocol.v \
    ../rtl/top_watchdog_kiwi1p5.v \
    ../tb/tb_uart_host.sv \
    ../tb/tb_top.sv

vsim work.tb_top

add wave -r sim:/tb_top/*
run -all