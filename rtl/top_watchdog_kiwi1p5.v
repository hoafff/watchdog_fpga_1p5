module top_watchdog_kiwi1p5 #(
    parameter integer CLK_HZ          = 27000000,
    parameter integer UART_BAUD       = 9600,
    parameter integer BTN_DEBOUNCE_MS = 10,
    parameter integer POR_CYCLES      = 1024
) (
    input  wire clk_27m,
    input  wire btn_wdi_n,
    input  wire btn_en_n,
    input  wire uart_rx_i,
    output wire uart_tx_o,
    output wire led_wdo_o,
    output wire led_enout_o
);

    reg [15:0] por_cnt_r = 16'd0;
    reg        rst_n_r   = 1'b0;

    wire tick_us_w;
    wire tick_ms_w;

    wire btn_wdi_level_w;
    wire btn_wdi_fall_w;
    wire btn_en_level_w;
    wire btn_en_fall_w;

    wire        reg_en_sw_w;
    wire        reg_wdi_src_w;
    wire [31:0] reg_twd_ms_w;
    wire [31:0] reg_trst_ms_w;
    wire [15:0] reg_arm_delay_us_w;
    wire        reg_clr_fault_pulse_w;
    wire        reg_wr_ack_w;
    wire        reg_rd_ack_w;
    wire        reg_access_err_w;
    wire [31:0] reg_rdata_w;

    wire        en_effective_w;
    wire        wdo_logic_w;
    wire        enout_logic_w;
    wire        fault_active_w;
    wire        last_kick_src_w;
    wire [1:0]  wd_state_w;

    wire [7:0]  rx_data_w;
    wire        rx_valid_w;
    wire        rx_frame_err_w;

    wire [7:0]  proto_tx_data_w;
    wire        proto_tx_start_w;
    wire        proto_wr_en_w;
    wire [7:0]  proto_wr_addr_w;
    wire [31:0] proto_wr_data_w;
    wire        proto_uart_kick_pulse_w;

    wire        tx_busy_w;
    wire        tx_done_w;

    always @(posedge clk_27m) begin
        if (!rst_n_r) begin
            if (por_cnt_r >= (POR_CYCLES - 1)) begin
                rst_n_r <= 1'b1;
            end else begin
                por_cnt_r <= por_cnt_r + 16'd1;
            end
        end
    end

    assign en_effective_w = reg_en_sw_w & btn_en_level_w;

    timebase_gen #(
        .CLK_HZ(CLK_HZ)
    ) u_timebase_gen (
        .clk    (clk_27m),
        .rst_n  (rst_n_r),
        .tick_us(tick_us_w),
        .tick_ms(tick_ms_w)
    );

    button_conditioner #(
        .CLK_HZ     (CLK_HZ),
        .DEBOUNCE_MS(BTN_DEBOUNCE_MS)
    ) u_button_wdi (
        .clk           (clk_27m),
        .rst_n         (rst_n_r),
        .btn_i         (btn_wdi_n),
        .level_o       (btn_wdi_level_w),
        .falling_edge_o(btn_wdi_fall_w)
    );

    button_conditioner #(
        .CLK_HZ     (CLK_HZ),
        .DEBOUNCE_MS(BTN_DEBOUNCE_MS)
    ) u_button_en (
        .clk           (clk_27m),
        .rst_n         (rst_n_r),
        .btn_i         (btn_en_n),
        .level_o       (btn_en_level_w),
        .falling_edge_o(btn_en_fall_w)
    );

    watchdog_core u_watchdog_core (
        .clk              (clk_27m),
        .rst_n            (rst_n_r),
        .tick_us_i        (tick_us_w),
        .tick_ms_i        (tick_ms_w),
        .en_effective_i   (en_effective_w),
        .wdi_src_i        (reg_wdi_src_w),
        .btn_kick_fall_i  (btn_wdi_fall_w),
        .uart_kick_pulse_i(proto_uart_kick_pulse_w),
        .clr_fault_pulse_i(reg_clr_fault_pulse_w),
        .twd_ms_i         (reg_twd_ms_w),
        .trst_ms_i        (reg_trst_ms_w),
        .arm_delay_us_i   (reg_arm_delay_us_w),
        .wdo_o            (wdo_logic_w),
        .enout_o          (enout_logic_w),
        .fault_active_o   (fault_active_w),
        .last_kick_src_o  (last_kick_src_w),
        .state_o          (wd_state_w)
    );

    regfile u_regfile (
        .clk             (clk_27m),
        .rst_n           (rst_n_r),
        .wr_en_i         (proto_wr_en_w),
        .rd_en_i         (1'b0),
        .addr_i          (proto_wr_addr_w),
        .wdata_i         (proto_wr_data_w),
        .en_effective_i  (en_effective_w),
        .fault_active_i  (fault_active_w),
        .enout_i         (enout_logic_w),
        .wdo_i           (wdo_logic_w),
        .last_kick_src_i (last_kick_src_w),
        .en_sw_o         (reg_en_sw_w),
        .wdi_src_o       (reg_wdi_src_w),
        .clr_fault_pulse_o(reg_clr_fault_pulse_w),
        .wr_ack_o        (reg_wr_ack_w),
        .rd_ack_o        (reg_rd_ack_w),
        .access_err_o    (reg_access_err_w),
        .rdata_o         (reg_rdata_w),
        .twd_ms_o        (reg_twd_ms_w),
        .trst_ms_o       (reg_trst_ms_w),
        .arm_delay_us_o  (reg_arm_delay_us_w)
    );

    uart_rx #(
        .CLK_HZ   (CLK_HZ),
        .BAUD_RATE(UART_BAUD)
    ) u_uart_rx (
        .clk        (clk_27m),
        .rst_n      (rst_n_r),
        .rx_i       (uart_rx_i),
        .data_o     (rx_data_w),
        .valid_o    (rx_valid_w),
        .frame_err_o(rx_frame_err_w)
    );

    uart_protocol #(
        .CLK_HZ          (CLK_HZ),
        .FRAME_TIMEOUT_MS(20)
    ) u_uart_protocol (
        .clk              (clk_27m),
        .rst_n            (rst_n_r),
        .rx_data_i        (rx_data_w),
        .rx_valid_i       (rx_valid_w),
        .rx_frame_err_i   (rx_frame_err_w),
        .tx_busy_i        (tx_busy_w),
        .en_sw_i          (reg_en_sw_w),
        .wdi_src_i        (reg_wdi_src_w),
        .twd_ms_i         (reg_twd_ms_w),
        .trst_ms_i        (reg_trst_ms_w),
        .arm_delay_us_i   (reg_arm_delay_us_w),
        .en_effective_i   (en_effective_w),
        .fault_active_i   (fault_active_w),
        .enout_i          (enout_logic_w),
        .wdo_i            (wdo_logic_w),
        .last_kick_src_i  (last_kick_src_w),
        .tx_data_o        (proto_tx_data_w),
        .tx_start_o       (proto_tx_start_w),
        .wr_en_o          (proto_wr_en_w),
        .wr_addr_o        (proto_wr_addr_w),
        .wr_data_o        (proto_wr_data_w),
        .uart_kick_pulse_o(proto_uart_kick_pulse_w)
    );

    uart_tx #(
        .CLK_HZ   (CLK_HZ),
        .BAUD_RATE(UART_BAUD)
    ) u_uart_tx (
        .clk    (clk_27m),
        .rst_n  (rst_n_r),
        .data_i (proto_tx_data_w),
        .start_i(proto_tx_start_w),
        .tx_o   (uart_tx_o),
        .busy_o (tx_busy_w),
        .done_o (tx_done_w)
    );

    assign led_wdo_o   = ~wdo_logic_w;
    assign led_enout_o = enout_logic_w;

endmodule
