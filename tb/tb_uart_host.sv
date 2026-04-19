module tb_uart_host #(
    parameter int CLK_HZ    = 1_000_000,
    parameter int BAUD_RATE = 9600
) (
    input  logic clk,
    input  logic rst_n,
    output logic tx_o,
    input  logic rx_i
);

    localparam int CLKS_PER_BIT  = (CLK_HZ + (BAUD_RATE / 2)) / BAUD_RATE;
    localparam int HALF_BIT_WAIT = (CLKS_PER_BIT / 2);

    byte rx_queue[$];

    initial begin
        tx_o = 1'b1;
    end

    task automatic uart_send_byte(input byte data);
        int i;
        begin
            tx_o <= 1'b0;
            repeat (CLKS_PER_BIT) @(posedge clk);
            for (i = 0; i < 8; i++) begin
                tx_o <= data[i];
                repeat (CLKS_PER_BIT) @(posedge clk);
            end
            tx_o <= 1'b1;
            repeat (CLKS_PER_BIT) @(posedge clk);
        end
    endtask

    task automatic uart_send_frame(
        input byte cmd,
        input byte addr,
        input byte len,
        input byte data0,
        input byte data1,
        input byte data2,
        input byte data3
    );
        byte chk;
        begin
            chk = cmd ^ addr ^ len;
            uart_send_byte(8'h55);
            uart_send_byte(cmd);
            uart_send_byte(addr);
            uart_send_byte(len);
            if (len > 0) begin uart_send_byte(data0); chk ^= data0; end
            if (len > 1) begin uart_send_byte(data1); chk ^= data1; end
            if (len > 2) begin uart_send_byte(data2); chk ^= data2; end
            if (len > 3) begin uart_send_byte(data3); chk ^= data3; end
            uart_send_byte(chk);
        end
    endtask

    task automatic uart_send_frame_bad_chk(
        input byte cmd,
        input byte addr,
        input byte len,
        input byte data0,
        input byte data1,
        input byte data2,
        input byte data3
    );
        byte chk;
        begin
            chk = cmd ^ addr ^ len ^ 8'hA5;
            uart_send_byte(8'h55);
            uart_send_byte(cmd);
            uart_send_byte(addr);
            uart_send_byte(len);
            if (len > 0) begin uart_send_byte(data0); chk ^= data0; end
            if (len > 1) begin uart_send_byte(data1); chk ^= data1; end
            if (len > 2) begin uart_send_byte(data2); chk ^= data2; end
            if (len > 3) begin uart_send_byte(data3); chk ^= data3; end
            uart_send_byte(chk);
        end
    endtask

    task automatic rx_capture_one_byte(output byte data);
        int i;
        begin
            data = 8'h00;

            while (rx_i === 1'b1) @(posedge clk);

            repeat (HALF_BIT_WAIT) @(posedge clk);
            repeat (CLKS_PER_BIT)  @(posedge clk);

            for (i = 0; i < 8; i++) begin
                data[i] = rx_i;
                if (i != 7) begin
                    repeat (CLKS_PER_BIT) @(posedge clk);
                end
            end

            repeat (CLKS_PER_BIT) @(posedge clk);
            if (rx_i !== 1'b1) begin
                $fatal(1, "UART RESP stop bit error: got %0b", rx_i);
            end

            rx_queue.push_back(data);
        end
    endtask

    task automatic rx_capture_n_bytes(input int nbytes);
        byte tmp;
        int k;
        begin
            for (k = 0; k < nbytes; k++) begin
                rx_capture_one_byte(tmp);
            end
        end
    endtask

    task automatic rx_expect_ok_frame(
        input byte exp_cmd,
        input byte exp_addr,
        input byte exp_len
    );
        byte chk;
        byte b;
        int  i;
        begin
            chk = exp_cmd ^ exp_addr ^ exp_len;
            rx_capture_one_byte(b);
            if (b !== 8'h55) $fatal(1, "UART RESP sync mismatch: got %02x", b);
            rx_capture_one_byte(b);
            if (b !== exp_cmd) $fatal(1, "UART RESP cmd mismatch: got %02x exp %02x", b, exp_cmd);
            rx_capture_one_byte(b);
            if (b !== exp_addr) $fatal(1, "UART RESP addr mismatch: got %02x exp %02x", b, exp_addr);
            rx_capture_one_byte(b);
            if (b !== exp_len) $fatal(1, "UART RESP len mismatch: got %02x exp %02x", b, exp_len);
            for (i = 0; i < exp_len; i++) begin
                rx_capture_one_byte(b);
                chk ^= b;
            end
            rx_capture_one_byte(b);
            if (b !== chk) $fatal(1, "UART RESP chk mismatch: got %02x exp %02x", b, chk);
        end
    endtask

    task automatic rx_expect_ok_frame_data(
        input byte exp_cmd,
        input byte exp_addr,
        input byte exp_len,
        input byte exp_data0,
        input byte exp_data1,
        input byte exp_data2,
        input byte exp_data3
    );
        byte chk;
        byte b;
        byte exp_byte;
        int  i;
        begin
            chk = exp_cmd ^ exp_addr ^ exp_len;
            rx_capture_one_byte(b);
            if (b !== 8'h55) $fatal(1, "UART RESP sync mismatch: got %02x", b);
            rx_capture_one_byte(b);
            if (b !== exp_cmd) $fatal(1, "UART RESP cmd mismatch: got %02x exp %02x", b, exp_cmd);
            rx_capture_one_byte(b);
            if (b !== exp_addr) $fatal(1, "UART RESP addr mismatch: got %02x exp %02x", b, exp_addr);
            rx_capture_one_byte(b);
            if (b !== exp_len) $fatal(1, "UART RESP len mismatch: got %02x exp %02x", b, exp_len);

            for (i = 0; i < exp_len; i++) begin
                case (i)
                    0: exp_byte = exp_data0;
                    1: exp_byte = exp_data1;
                    2: exp_byte = exp_data2;
                    default: exp_byte = exp_data3;
                endcase
                rx_capture_one_byte(b);
                if (b !== exp_byte) begin
                    $fatal(1, "UART RESP data[%0d] mismatch: got %02x exp %02x", i, b, exp_byte);
                end
                chk ^= b;
            end

            rx_capture_one_byte(b);
            if (b !== chk) $fatal(1, "UART RESP chk mismatch: got %02x exp %02x", b, chk);
        end
    endtask

    task automatic rx_expect_ok_frame32(
        input byte exp_cmd,
        input byte exp_addr,
        input logic [31:0] exp_data
    );
        begin
            rx_expect_ok_frame_data(exp_cmd, exp_addr, 8'd4,
                                    exp_data[31:24], exp_data[23:16], exp_data[15:8], exp_data[7:0]);
        end
    endtask

    task automatic rx_expect_ok_frame16(
        input byte exp_cmd,
        input byte exp_addr,
        input logic [15:0] exp_data
    );
        begin
            rx_expect_ok_frame_data(exp_cmd, exp_addr, 8'd2,
                                    exp_data[15:8], exp_data[7:0], 8'h00, 8'h00);
        end
    endtask

    task automatic rx_expect_err_frame(
        input byte exp_orig_cmd,
        input byte exp_err_code
    );
        byte chk;
        byte b;
        begin
            chk = 8'h7F ^ exp_orig_cmd ^ 8'h01 ^ exp_err_code;
            rx_capture_one_byte(b);
            if (b !== 8'h55) $fatal(1, "UART ERR sync mismatch: got %02x", b);
            rx_capture_one_byte(b);
            if (b !== 8'h7F) $fatal(1, "UART ERR cmd mismatch: got %02x", b);
            rx_capture_one_byte(b);
            if (b !== exp_orig_cmd) $fatal(1, "UART ERR orig cmd mismatch: got %02x", b);
            rx_capture_one_byte(b);
            if (b !== 8'h01) $fatal(1, "UART ERR len mismatch: got %02x", b);
            rx_capture_one_byte(b);
            if (b !== exp_err_code) $fatal(1, "UART ERR code mismatch: got %02x exp %02x", b, exp_err_code);
            rx_capture_one_byte(b);
            if (b !== chk) $fatal(1, "UART ERR chk mismatch: got %02x exp %02x", b, chk);
        end
    endtask

endmodule