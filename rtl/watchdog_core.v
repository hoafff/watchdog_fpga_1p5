module watchdog_core (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        tick_us_i,
    input  wire        tick_ms_i,
    input  wire        en_effective_i,
    input  wire        wdi_src_i,
    input  wire        btn_kick_fall_i,
    input  wire        uart_kick_pulse_i,
    input  wire        clr_fault_pulse_i,
    input  wire [31:0] twd_ms_i,
    input  wire [31:0] trst_ms_i,
    input  wire [15:0] arm_delay_us_i,
    output wire        wdo_o,
    output wire        enout_o,
    output wire        fault_active_o,
    output reg         last_kick_src_o,
    output reg  [1:0]  state_o
);

    localparam [1:0] ST_DISABLED   = 2'd0;
    localparam [1:0] ST_ARM_DELAY  = 2'd1;
    localparam [1:0] ST_MONITOR    = 2'd2;
    localparam [1:0] ST_FAULT_HOLD = 2'd3;

    reg [31:0] wd_cnt_ms_r;
    reg [31:0] rst_cnt_ms_r;
    reg [15:0] arm_cnt_us_r;

    wire selected_kick_w;
    wire [31:0] twd_ms_eff_w;
    wire [31:0] trst_ms_eff_w;

    assign selected_kick_w = (wdi_src_i == 1'b0) ? btn_kick_fall_i : uart_kick_pulse_i;
    assign twd_ms_eff_w    = (twd_ms_i  == 32'd0) ? 32'd1 : twd_ms_i;
    assign trst_ms_eff_w   = (trst_ms_i == 32'd0) ? 32'd1 : trst_ms_i;

    assign wdo_o          = (state_o == ST_FAULT_HOLD) ? 1'b0 : 1'b1;
    assign enout_o        = ((state_o == ST_MONITOR) || (state_o == ST_FAULT_HOLD)) ? 1'b1 : 1'b0;
    assign fault_active_o = (state_o == ST_FAULT_HOLD);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_o          <= ST_DISABLED;
            wd_cnt_ms_r      <= 32'd0;
            rst_cnt_ms_r     <= 32'd0;
            arm_cnt_us_r     <= 16'd0;
            last_kick_src_o  <= 1'b0;
        end else begin
            case (state_o)
                ST_DISABLED: begin
                    wd_cnt_ms_r  <= 32'd0;
                    rst_cnt_ms_r <= 32'd0;
                    arm_cnt_us_r <= 16'd0;

                    if (en_effective_i) begin
                        if (arm_delay_us_i == 16'd0) begin
                            state_o <= ST_MONITOR;
                        end else begin
                            state_o <= ST_ARM_DELAY;
                        end
                    end
                end

                ST_ARM_DELAY: begin
                    wd_cnt_ms_r  <= 32'd0;
                    rst_cnt_ms_r <= 32'd0;

                    if (!en_effective_i) begin
                        arm_cnt_us_r <= 16'd0;
                        state_o      <= ST_DISABLED;
                    end else if (arm_delay_us_i == 16'd0) begin
                        arm_cnt_us_r <= 16'd0;
                        state_o      <= ST_MONITOR;
                    end else if (tick_us_i) begin
                        if (arm_cnt_us_r + 16'd1 >= arm_delay_us_i) begin
                            arm_cnt_us_r <= 16'd0;
                            state_o      <= ST_MONITOR;
                        end else begin
                            arm_cnt_us_r <= arm_cnt_us_r + 16'd1;
                        end
                    end
                end

                ST_MONITOR: begin
                    arm_cnt_us_r  <= 16'd0;
                    rst_cnt_ms_r  <= 32'd0;

                    if (!en_effective_i) begin
                        wd_cnt_ms_r <= 32'd0;
                        state_o     <= ST_DISABLED;
                    end else if (selected_kick_w) begin
                        wd_cnt_ms_r     <= 32'd0;
                        last_kick_src_o <= wdi_src_i;
                    end else if (tick_ms_i) begin
                        if (wd_cnt_ms_r + 32'd1 >= twd_ms_eff_w) begin
                            wd_cnt_ms_r  <= 32'd0;
                            rst_cnt_ms_r <= 32'd0;
                            state_o      <= ST_FAULT_HOLD;
                        end else begin
                            wd_cnt_ms_r <= wd_cnt_ms_r + 32'd1;
                        end
                    end
                end

                ST_FAULT_HOLD: begin
                    arm_cnt_us_r <= 16'd0;
                    wd_cnt_ms_r  <= 32'd0;

                    if (!en_effective_i) begin
                        rst_cnt_ms_r <= 32'd0;
                        state_o      <= ST_DISABLED;
                    end else if (clr_fault_pulse_i) begin
                        rst_cnt_ms_r <= 32'd0;
                        state_o      <= ST_MONITOR;
                    end else if (tick_ms_i) begin
                        if (rst_cnt_ms_r + 32'd1 >= trst_ms_eff_w) begin
                            rst_cnt_ms_r <= 32'd0;
                            state_o      <= ST_MONITOR;
                        end else begin
                            rst_cnt_ms_r <= rst_cnt_ms_r + 32'd1;
                        end
                    end
                end

                default: begin
                    state_o <= ST_DISABLED;
                end
            endcase
        end
    end

endmodule
