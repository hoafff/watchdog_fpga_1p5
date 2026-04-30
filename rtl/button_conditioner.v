module button_conditioner #(
    parameter integer CLK_HZ      = 27000000,
    parameter integer DEBOUNCE_MS = 10
) (
    input  wire clk,
    input  wire rst_n,
    input  wire btn_i,
    output reg  level_o,
    output reg  falling_edge_o
);

    localparam integer DEBOUNCE_CYCLES_RAW = (CLK_HZ / 1000) * DEBOUNCE_MS;
    localparam integer DEBOUNCE_CYCLES     = (DEBOUNCE_CYCLES_RAW < 1) ? 1 : DEBOUNCE_CYCLES_RAW;

    reg sync_ff1;
    reg sync_ff2;
    reg [31:0] stable_cnt;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sync_ff1        <= 1'b1;
            sync_ff2        <= 1'b1;
            stable_cnt      <= 32'd0;
            level_o         <= 1'b1;
            falling_edge_o  <= 1'b0;
        end else begin
            sync_ff1       <= btn_i;
            sync_ff2       <= sync_ff1;
            falling_edge_o <= 1'b0;

            if (sync_ff2 == level_o) begin
                stable_cnt <= 32'd0;
            end else begin
                if (stable_cnt >= (DEBOUNCE_CYCLES - 1)) begin
                    stable_cnt <= 32'd0;
                    if ((level_o == 1'b1) && (sync_ff2 == 1'b0)) begin
                        falling_edge_o <= 1'b1;
                    end
                    level_o <= sync_ff2;
                end else begin
                    stable_cnt <= stable_cnt + 32'd1;
                end
            end
        end
    end

endmodule
