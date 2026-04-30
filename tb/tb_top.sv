`timescale 1ns/1ps

module tb_top;

    localparam int CLK_HZ             = 1_000_000;
    localparam int UART_BAUD          = 9600;
    localparam int BTN_DEBOUNCE_MS    = 1;
    localparam int POR_CYCLES         = 8;
    localparam time CLK_PERIOD        = 1000ns;

    logic clk_27m;
    logic btn_wdi_n;
    logic btn_en_n;
    logic uart_rx_i;
    wire  uart_tx_o;
    wire  led_wdo_o;
    wire  led_enout_o;

    top_watchdog_kiwi1p5 #(
        .CLK_HZ          (CLK_HZ),
        .UART_BAUD       (UART_BAUD),
        .BTN_DEBOUNCE_MS (BTN_DEBOUNCE_MS),
        .POR_CYCLES      (POR_CYCLES)
    ) dut (
        .clk_27m     (clk_27m),
        .btn_wdi_n   (btn_wdi_n),
        .btn_en_n    (btn_en_n),
        .uart_rx_i   (uart_rx_i),
        .uart_tx_o   (uart_tx_o),
        .led_wdo_o   (led_wdo_o),
        .led_enout_o (led_enout_o)
    );

    tb_uart_host #(
        .CLK_HZ    (CLK_HZ),
        .BAUD_RATE (UART_BAUD)
    ) host (
        .clk   (clk_27m),
        .rst_n (dut.rst_n_r),
        .tx_o  (uart_rx_i),
        .rx_i  (uart_tx_o)
    );

    initial begin
        clk_27m = 1'b0;
        forever #(CLK_PERIOD/2) clk_27m = ~clk_27m;
    end

    initial begin
        $dumpfile("tb_top.vcd");
        $dumpvars(0, tb_top);
    end

    `include "tb_tasks.svh"

    initial begin
        $display("[TB] start");
        btn_wdi_n = 1'b1;
        btn_en_n  = 1'b1;

        wait (dut.rst_n_r == 1'b1);
        wait_ms(2);

        // Case 1: reset default
        check_reset_defaults();
        $display("[TB] Case1 pass");

        // Case 2: enable -> arm_delay -> MONITOR, WDI ignored during arm_delay
        $display("[TB] Case2 start");

        uart_write32(8'h04, 32'd80);
        uart_write32(8'h08, 32'd20);
        uart_write16(8'h0C, 16'd40000);
        uart_write32(8'h00, 32'h0000_0001);

        if (dut.wd_state_w !== 2'd1)
            $fatal(1, "Case2 did not enter ARM_DELAY");

        if (dut.enout_logic_w !== 1'b0)
            $fatal(1, "Case2 ENOUT asserted too early");

        wait_ms(5);
        press_btn_wdi();
        if (dut.wd_state_w !== 2'd1)
            $fatal(1, "Case2 WDI during arm_delay was not ignored");
        if (dut.enout_logic_w !== 1'b0)
            $fatal(1, "Case2 ENOUT asserted after ignored arm_delay kick");

        fork
            begin
                wait (dut.wd_state_w == 2'd2);
            end
            begin
                wait_ms(100);
                $fatal(1, "Case2 timeout waiting for MONITOR");
            end
        join_any
        disable fork;

        if (dut.enout_logic_w !== 1'b1)
            $fatal(1, "Case2 ENOUT not asserted");

        if (dut.wdo_logic_w !== 1'b1)
            $fatal(1, "Case2 WDO asserted unexpectedly");

        $display("[TB] Case2 pass");

        // Case 3: normal kick via button
        repeat (3) begin
            wait_ms(3);
            press_btn_wdi();
            if (dut.fault_active_w !== 1'b0)
                $fatal(1, "Case3 unexpected fault");
            if (dut.last_kick_src_w !== 1'b0)
                $fatal(1, "Case3 LAST_KICK_SRC wrong");
        end
        $display("[TB] Case3 pass");

        // Case 4: timeout then hold then recover
        wait_ms(dut.reg_twd_ms_w + 5);
        if (dut.fault_active_w !== 1'b1)
            $fatal(1, "Case4 fault did not assert");
        if (dut.wdo_logic_w !== 1'b0)
            $fatal(1, "Case4 WDO not low in fault");

        wait_ms(dut.reg_trst_ms_w + 5);
        if (dut.fault_active_w !== 1'b0)
            $fatal(1, "Case4 fault did not clear after tRST");
        if (dut.wdo_logic_w !== 1'b1)
            $fatal(1, "Case4 WDO not released after tRST");
        $display("[TB] Case4 pass");

        // Case 5: disable while monitoring
        hold_btn_en_low();
        if (dut.en_effective_w !== 1'b0)
            $fatal(1, "Case5 EN_EFFECTIVE not low after disable button");
        if (dut.wd_state_w !== 2'd0)
            $fatal(1, "Case5 not back to DISABLED");
        if (dut.enout_logic_w !== 1'b0)
            $fatal(1, "Case5 ENOUT not low after disable");
        $display("[TB] Case5 pass");

        // Case 6: UART error paths while WDI source is still button
        uart_kick_expect_not_allow();
        uart_read_bad_addr_expect_err(8'h20);
        uart_write_bad_len_expect_err(8'h04);
        uart_write_zero_timeout_expect_err(8'h04);
        uart_write_zero_timeout_expect_err(8'h08);
        $display("[TB] Case6 pass");

        // Re-enable with UART source
        uart_write32(8'h00, 32'h0000_0003);
        release_btn_en();

        if (dut.wd_state_w !== 2'd1)
            $fatal(1, "Re-enable did not enter ARM_DELAY");

        fork
            begin
                wait (dut.wd_state_w == 2'd2);
            end
            begin
                wait_ms(100);
                $fatal(1, "Re-enable timeout waiting for MONITOR");
            end
        join_any
        disable fork;

        if (dut.enout_logic_w !== 1'b1)
            $fatal(1, "Re-enable ENOUT not asserted");

        // Case 7: UART read/write reg with payload checking
// Use a tWD value large enough to cover multiple UART command/response frames at 9600 bps.
uart_write32(8'h04, 32'd200);
uart_read_expect32(8'h04, 32'd200);
uart_write32(8'h08, 32'd50);
uart_read_expect32(8'h08, 32'd50);
uart_write16(8'h0C, 16'd25);
uart_read_expect16(8'h0C, 16'd25);
$display("[TB] Case7 pass");

        // Case 8: UART KICK + GET_STATUS
        uart_kick_expect_ok();
        wait_ms(1);
        if (dut.last_kick_src_w !== 1'b1)
            $fatal(1, "Case8 LAST_KICK_SRC not UART");
        uart_get_status_expect_ok();
        $display("[TB] Case8 pass");

        // Case 9: programmed tWD_ms affects real timeout timing
// Re-kick here so the timing measurement starts from a known point.
// uart_kick_expect_ok() itself takes several ms because the response is serialized over UART.
uart_kick_expect_ok();

wait_ms(100);
if (dut.fault_active_w !== 1'b0)
    $fatal(1, "Case9 fault asserted before programmed tWD_ms");

wait_ms(120);
if (dut.fault_active_w !== 1'b1)
    $fatal(1, "Case9 fault did not assert after programmed tWD_ms");

$display("[TB] Case9 pass");

        // Case 10: disable while fault is active releases WDO and ENOUT
        hold_btn_en_low();
        if (dut.wd_state_w !== 2'd0)
            $fatal(1, "Case10 disable during fault did not enter DISABLED");
        if (dut.wdo_logic_w !== 1'b1)
            $fatal(1, "Case10 WDO not released after disable during fault");
        if (dut.enout_logic_w !== 1'b0)
            $fatal(1, "Case10 ENOUT not low after disable during fault");
        $display("[TB] Case10 pass");

        // Re-enable again for CLR_FAULT test
        release_btn_en();
        fork
            begin
                wait (dut.wd_state_w == 2'd2);
            end
            begin
                wait_ms(20);
                $fatal(1, "Re-enable before Case11 timeout waiting for MONITOR");
            end
        join_any
        disable fork;

        uart_kick_expect_ok();
        wait_ms(dut.reg_twd_ms_w + 5);
        if (dut.fault_active_w !== 1'b1)
            $fatal(1, "Case11 expected fault before clear");

        // Case 11: CLR_FAULT clears WDO immediately
        host.uart_send_frame(8'h01, 8'h00, 8'd4, 8'h00, 8'h00, 8'h00, 8'h07);
        @(posedge clk_27m);
        host.rx_expect_ok_frame32(8'h81, 8'h10, dut_status_word());

        wait_ms(1);
        if (dut.fault_active_w !== 1'b0)
            $fatal(1, "Case11 CLR_FAULT did not clear");
        uart_get_status_expect_ok();
        $display("[TB] Case11 pass");

        // Case 12: checksum error response
        host.uart_send_frame_bad_chk(8'h04, 8'h10, 8'd0, 8'h00, 8'h00, 8'h00, 8'h00);
        host.rx_expect_err_frame(8'h04, 8'h03);
        $display("[TB] Case12 pass");

        $display("[TB] all cases pass");
        #10000;
        $finish;
    end

endmodule
