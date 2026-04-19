// Reusable testbench tasks for tb_top.sv.
// Include this file inside the tb_top module body after DUT and host instances.

`ifndef TB_TASKS_SVH
`define TB_TASKS_SVH

    function automatic [31:0] dut_status_word;
        begin
            dut_status_word = {27'd0, dut.last_kick_src_w, dut.wdo_logic_w, dut.enout_logic_w, dut.fault_active_w, dut.en_effective_w};
        end
    endfunction

    task automatic wait_us(input int n_us);
        repeat (n_us) @(posedge dut.tick_us_w);
    endtask

    task automatic wait_ms(input int n_ms);
        repeat (n_ms) @(posedge dut.tick_ms_w);
    endtask

    task automatic press_btn_wdi;
        begin
            btn_wdi_n <= 1'b0;
            wait_ms(2);
            btn_wdi_n <= 1'b1;
            wait_ms(2);
        end
    endtask

    task automatic hold_btn_en_low;
        begin
            btn_en_n <= 1'b0;
            wait_ms(2);
        end
    endtask

    task automatic release_btn_en;
        begin
            btn_en_n <= 1'b1;
            wait_ms(2);
        end
    endtask

    task automatic uart_write32(input byte addr, input logic [31:0] data);
        begin
            host.uart_send_frame(8'h01, addr, 8'd4, data[31:24], data[23:16], data[15:8], data[7:0]);
            @(posedge clk_27m);
            host.rx_expect_ok_frame32(8'h81, 8'h10, dut_status_word());
        end
    endtask

    task automatic uart_write16(input byte addr, input logic [15:0] data);
        begin
            host.uart_send_frame(8'h01, addr, 8'd2, data[15:8], data[7:0], 8'h00, 8'h00);
            @(posedge clk_27m);
            host.rx_expect_ok_frame32(8'h81, 8'h10, dut_status_word());
        end
    endtask

    task automatic uart_read_expect32(input byte addr, input logic [31:0] exp_data);
        begin
            host.uart_send_frame(8'h02, addr, 8'd0, 8'h00, 8'h00, 8'h00, 8'h00);
            host.rx_expect_ok_frame32(8'h82, addr, exp_data);
        end
    endtask

    task automatic uart_read_expect16(input byte addr, input logic [15:0] exp_data);
        begin
            host.uart_send_frame(8'h02, addr, 8'd0, 8'h00, 8'h00, 8'h00, 8'h00);
            host.rx_expect_ok_frame16(8'h82, addr, exp_data);
        end
    endtask

    task automatic uart_get_status_expect_ok;
        begin
            host.uart_send_frame(8'h04, 8'h10, 8'd0, 8'h00, 8'h00, 8'h00, 8'h00);
            host.rx_expect_ok_frame32(8'h84, 8'h10, dut_status_word());
        end
    endtask

    task automatic uart_kick_expect_ok;
        begin
            host.uart_send_frame(8'h03, 8'h00, 8'd0, 8'h00, 8'h00, 8'h00, 8'h00);
            @(posedge clk_27m);
            host.rx_expect_ok_frame32(8'h83, 8'h10, dut_status_word());
        end
    endtask

    task automatic check_reset_defaults;
        begin
            if (dut.reg_en_sw_w !== 1'b0)           $fatal(1, "Case1 EN_SW default wrong");
            if (dut.reg_wdi_src_w !== 1'b0)         $fatal(1, "Case1 WDI_SRC default wrong");
            if (dut.reg_twd_ms_w !== 32'd1600)      $fatal(1, "Case1 tWD default wrong");
            if (dut.reg_trst_ms_w !== 32'd200)      $fatal(1, "Case1 tRST default wrong");
            if (dut.reg_arm_delay_us_w !== 16'd150) $fatal(1, "Case1 arm delay default wrong");
            if (dut.en_effective_w !== 1'b0)        $fatal(1, "Case1 EN_EFFECTIVE wrong");
            if (dut.wdo_logic_w !== 1'b1)           $fatal(1, "Case1 WDO default wrong");
            if (dut.enout_logic_w !== 1'b0)         $fatal(1, "Case1 ENOUT default wrong");
        end
    endtask

`endif