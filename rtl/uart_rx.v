module uart_rx #(
    parameter integer CLK_HZ    = 27000000,
    parameter integer BAUD_RATE = 9600
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       rx_i,
    output reg [7:0]  data_o,
    output reg        valid_o,
    output reg        frame_err_o
);

    localparam integer CLKS_PER_BIT  = (CLK_HZ + (BAUD_RATE / 2)) / BAUD_RATE;
    localparam integer CLKS_HALF_BIT = CLKS_PER_BIT / 2;

    localparam [1:0] ST_IDLE  = 2'd0;
    localparam [1:0] ST_START = 2'd1;
    localparam [1:0] ST_DATA  = 2'd2;
    localparam [1:0] ST_STOP  = 2'd3;

    reg [1:0]  state_r;
    reg [15:0] baud_cnt_r;
    reg [2:0]  bit_idx_r;
    reg [7:0]  shift_r;

    // UART RX is asynchronous to the FPGA clock. Synchronize it before
    // start-bit detection and sampling to reduce metastability risk.
    reg rx_meta_r;
    reg rx_sync_r;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_r     <= ST_IDLE;
            baud_cnt_r  <= 16'd0;
            bit_idx_r   <= 3'd0;
            shift_r     <= 8'd0;
            data_o      <= 8'd0;
            valid_o     <= 1'b0;
            frame_err_o <= 1'b0;
            rx_meta_r   <= 1'b1;
            rx_sync_r   <= 1'b1;
        end else begin
            rx_meta_r   <= rx_i;
            rx_sync_r   <= rx_meta_r;
            valid_o     <= 1'b0;
            frame_err_o <= 1'b0;

            case (state_r)
                ST_IDLE: begin
                    baud_cnt_r <= 16'd0;
                    bit_idx_r  <= 3'd0;
                    if (rx_sync_r == 1'b0) begin
                        state_r    <= ST_START;
                        baud_cnt_r <= 16'd0;
                    end
                end

                ST_START: begin
                    if (baud_cnt_r >= (CLKS_HALF_BIT - 1)) begin
                        if (rx_sync_r == 1'b0) begin
                            state_r    <= ST_DATA;
                            baud_cnt_r <= 16'd0;
                            bit_idx_r  <= 3'd0;
                        end else begin
                            state_r <= ST_IDLE;
                        end
                    end else begin
                        baud_cnt_r <= baud_cnt_r + 16'd1;
                    end
                end

                ST_DATA: begin
                    if (baud_cnt_r >= (CLKS_PER_BIT - 1)) begin
                        baud_cnt_r           <= 16'd0;
                        shift_r[bit_idx_r]   <= rx_sync_r;
                        if (bit_idx_r == 3'd7) begin
                            state_r <= ST_STOP;
                        end else begin
                            bit_idx_r <= bit_idx_r + 3'd1;
                        end
                    end else begin
                        baud_cnt_r <= baud_cnt_r + 16'd1;
                    end
                end

                ST_STOP: begin
                    if (baud_cnt_r >= (CLKS_PER_BIT - 1)) begin
                        state_r    <= ST_IDLE;
                        baud_cnt_r <= 16'd0;
                        if (rx_sync_r == 1'b1) begin
                            data_o  <= shift_r;
                            valid_o <= 1'b1;
                        end else begin
                            frame_err_o <= 1'b1;
                        end
                    end else begin
                        baud_cnt_r <= baud_cnt_r + 16'd1;
                    end
                end

                default: begin
                    state_r <= ST_IDLE;
                end
            endcase
        end
    end

endmodule
