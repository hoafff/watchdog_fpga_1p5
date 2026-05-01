module regfile #(
    parameter [31:0] DEFAULT_TWD_MS      = 32'd1600,
    parameter [31:0] DEFAULT_TRST_MS     = 32'd200,
    parameter [15:0] DEFAULT_ARM_DELAYUS = 16'd150
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        wr_en_i,
    input  wire        rd_en_i,
    input  wire [7:0]  addr_i,
    input  wire [31:0] wdata_i,
    input  wire        en_effective_i,
    input  wire        fault_active_i,
    input  wire        enout_i,
    input  wire        wdo_i,
    input  wire        last_kick_src_i,
    output wire        en_sw_o,
    output wire        wdi_src_o,
    output reg         clr_fault_pulse_o,
    output reg         wr_ack_o,
    output reg         rd_ack_o,
    output reg         access_err_o,
    output reg  [31:0] rdata_o,
    output reg  [31:0] twd_ms_o,
    output reg  [31:0] trst_ms_o,
    output reg  [15:0] arm_delay_us_o
);

    localparam [7:0] ADDR_CTRL      = 8'h00;
    localparam [7:0] ADDR_TWD_MS    = 8'h04;
    localparam [7:0] ADDR_TRST_MS   = 8'h08;
    localparam [7:0] ADDR_ARM_DELAY = 8'h0C;
    localparam [7:0] ADDR_STATUS    = 8'h10;

    reg ctrl_en_sw_r;
    reg ctrl_wdi_src_r;

    wire [31:0] ctrl_word_w;
    wire [31:0] status_word_w;

    assign en_sw_o   = ctrl_en_sw_r;
    assign wdi_src_o = ctrl_wdi_src_r;

    assign ctrl_word_w = {29'd0, 1'b0, ctrl_wdi_src_r, ctrl_en_sw_r};
    assign status_word_w = {27'd0, last_kick_src_i, wdo_i, enout_i, fault_active_i, en_effective_i};

    always @(*) begin
        case (addr_i)
            ADDR_CTRL:      rdata_o = ctrl_word_w;
            ADDR_TWD_MS:    rdata_o = twd_ms_o;
            ADDR_TRST_MS:   rdata_o = trst_ms_o;
            ADDR_ARM_DELAY: rdata_o = {16'd0, arm_delay_us_o};
            ADDR_STATUS:    rdata_o = status_word_w;
            default:        rdata_o = 32'd0;
        endcase
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ctrl_en_sw_r      <= 1'b0;
            ctrl_wdi_src_r    <= 1'b0;
            twd_ms_o          <= DEFAULT_TWD_MS;
            trst_ms_o         <= DEFAULT_TRST_MS;
            arm_delay_us_o    <= DEFAULT_ARM_DELAYUS;
            clr_fault_pulse_o <= 1'b0;
            wr_ack_o          <= 1'b0;
            rd_ack_o          <= 1'b0;
            access_err_o      <= 1'b0;
        end else begin
            // Tự động hạ xung clear khi watchdog core đã xác nhận xóa cờ fault
            if (!fault_active_i) begin
                clr_fault_pulse_o <= 1'b0;
            end

            wr_ack_o          <= 1'b0;
            rd_ack_o          <= 1'b0;
            access_err_o      <= 1'b0;

            if (wr_en_i) begin
                wr_ack_o <= 1'b1;
                case (addr_i)
                    ADDR_CTRL: begin
                        ctrl_en_sw_r   <= wdata_i[0];
                        ctrl_wdi_src_r <= wdata_i[1];
                        if (wdata_i[2]) begin
                            clr_fault_pulse_o <= 1'b1;
                        end
                    end

                    ADDR_TWD_MS: begin
                        if (wdata_i != 32'd0) begin
                            twd_ms_o <= wdata_i;
                        end else begin
                            access_err_o <= 1'b1;
                        end
                    end

                    ADDR_TRST_MS: begin
                        if (wdata_i != 32'd0) begin
                            trst_ms_o <= wdata_i;
                        end else begin
                            access_err_o <= 1'b1;
                        end
                    end

                    ADDR_ARM_DELAY: begin
                        arm_delay_us_o <= wdata_i[15:0];
                    end

                    ADDR_STATUS: begin
                        access_err_o <= 1'b1;
                    end

                    default: begin
                        access_err_o <= 1'b1;
                    end
                endcase
            end

            if (rd_en_i) begin
                rd_ack_o <= 1'b1;
                case (addr_i)
                    ADDR_CTRL,
                    ADDR_TWD_MS,
                    ADDR_TRST_MS,
                    ADDR_ARM_DELAY,
                    ADDR_STATUS: begin
                    end
                    default: begin
                        access_err_o <= 1'b1;
                    end
                endcase
            end
        end
    end

endmodule