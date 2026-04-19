module uart_tx #(
    parameter integer CLK_HZ    = 27000000,
    parameter integer BAUD_RATE = 9600
) (
    input  wire      clk,
    input  wire      rst_n,
    input  wire [7:0] data_i,
    input  wire      start_i,
    output reg       tx_o,
    output reg       busy_o,
    output reg       done_o
);

    localparam integer CLKS_PER_BIT = (CLK_HZ + (BAUD_RATE / 2)) / BAUD_RATE;

    localparam [1:0] ST_IDLE  = 2'd0;
    localparam [1:0] ST_START = 2'd1;
    localparam [1:0] ST_DATA  = 2'd2;
    localparam [1:0] ST_STOP  = 2'd3;

    reg [1:0]  state_r;
    reg [15:0] baud_cnt_r;
    reg [2:0]  bit_idx_r;
    reg [7:0]  shift_r;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_r    <= ST_IDLE;
            baud_cnt_r <= 16'd0;
            bit_idx_r  <= 3'd0;
            shift_r    <= 8'd0;
            tx_o       <= 1'b1;
            busy_o     <= 1'b0;
            done_o     <= 1'b0;
        end else begin
            done_o <= 1'b0;

            case (state_r)
                ST_IDLE: begin
                    tx_o       <= 1'b1;
                    busy_o     <= 1'b0;
                    baud_cnt_r <= 16'd0;
                    bit_idx_r  <= 3'd0;
                    if (start_i) begin
                        shift_r    <= data_i;
                        state_r    <= ST_START;
                        busy_o     <= 1'b1;
                        tx_o       <= 1'b0;
                        baud_cnt_r <= 16'd0;
                    end
                end

                ST_START: begin
                    tx_o   <= 1'b0;
                    busy_o <= 1'b1;
                    if (baud_cnt_r >= (CLKS_PER_BIT - 1)) begin
                        baud_cnt_r <= 16'd0;
                        bit_idx_r  <= 3'd0;
                        state_r    <= ST_DATA;
                        tx_o       <= shift_r[0];
                    end else begin
                        baud_cnt_r <= baud_cnt_r + 16'd1;
                    end
                end

                ST_DATA: begin
                    tx_o   <= shift_r[bit_idx_r];
                    busy_o <= 1'b1;
                    if (baud_cnt_r >= (CLKS_PER_BIT - 1)) begin
                        baud_cnt_r <= 16'd0;
                        if (bit_idx_r == 3'd7) begin
                            state_r <= ST_STOP;
                            tx_o    <= 1'b1;
                        end else begin
                            bit_idx_r <= bit_idx_r + 3'd1;
                        end
                    end else begin
                        baud_cnt_r <= baud_cnt_r + 16'd1;
                    end
                end

                ST_STOP: begin
                    tx_o   <= 1'b1;
                    busy_o <= 1'b1;
                    if (baud_cnt_r >= (CLKS_PER_BIT - 1)) begin
                        state_r    <= ST_IDLE;
                        baud_cnt_r <= 16'd0;
                        busy_o     <= 1'b0;
                        done_o     <= 1'b1;
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
