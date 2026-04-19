module timebase_gen #(
    parameter integer CLK_HZ = 27000000
) (
    input  wire clk,
    input  wire rst_n,
    output reg  tick_us,
    output reg  tick_ms
);

    localparam integer US_DIV = CLK_HZ / 1000000;
    localparam integer MS_DIV = CLK_HZ / 1000;

    reg [31:0] us_cnt;
    reg [31:0] ms_cnt;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            us_cnt  <= 32'd0;
            ms_cnt  <= 32'd0;
            tick_us <= 1'b0;
            tick_ms <= 1'b0;
        end else begin
            tick_us <= 1'b0;
            tick_ms <= 1'b0;

            if (us_cnt == (US_DIV - 1)) begin
                us_cnt  <= 32'd0;
                tick_us <= 1'b1;
            end else begin
                us_cnt <= us_cnt + 32'd1;
            end

            if (ms_cnt == (MS_DIV - 1)) begin
                ms_cnt  <= 32'd0;
                tick_ms <= 1'b1;
            end else begin
                ms_cnt <= ms_cnt + 32'd1;
            end
        end
    end

endmodule
