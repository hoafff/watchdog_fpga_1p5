module uart_protocol #(
    parameter integer CLK_HZ           = 27000000,
    parameter integer FRAME_TIMEOUT_MS = 20
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [7:0]  rx_data_i,
    input  wire        rx_valid_i,
    input  wire        rx_frame_err_i,
    input  wire        tx_busy_i,

    input  wire        en_sw_i,
    input  wire        wdi_src_i,
    input  wire [31:0] twd_ms_i,
    input  wire [31:0] trst_ms_i,
    input  wire [15:0] arm_delay_us_i,
    input  wire        en_effective_i,
    input  wire        fault_active_i,
    input  wire        enout_i,
    input  wire        wdo_i,
    input  wire        last_kick_src_i,

    output reg  [7:0]  tx_data_o,
    output reg         tx_start_o,
    output reg         wr_en_o,
    output reg  [7:0]  wr_addr_o,
    output reg  [31:0] wr_data_o,
    output reg         uart_kick_pulse_o
);

    localparam [7:0] CMD_WRITE_REG  = 8'h01;
    localparam [7:0] CMD_READ_REG   = 8'h02;
    localparam [7:0] CMD_KICK       = 8'h03;
    localparam [7:0] CMD_GET_STATUS = 8'h04;

    localparam [7:0] CMD_ERR        = 8'h7F;

    localparam [7:0] ERR_BAD_SYNC   = 8'h01;
    localparam [7:0] ERR_BAD_LEN    = 8'h02;
    localparam [7:0] ERR_BAD_CHK    = 8'h03;
    localparam [7:0] ERR_BAD_ADDR   = 8'h04;
    localparam [7:0] ERR_BAD_ACCESS = 8'h05;
    localparam [7:0] ERR_NOT_ALLOW  = 8'h06;
    localparam [7:0] ERR_UART_FRAME = 8'h07;

    localparam [7:0] ADDR_CTRL      = 8'h00;
    localparam [7:0] ADDR_TWD_MS    = 8'h04;
    localparam [7:0] ADDR_TRST_MS   = 8'h08;
    localparam [7:0] ADDR_ARM_DELAY = 8'h0C;
    localparam [7:0] ADDR_STATUS    = 8'h10;

    localparam [2:0] RX_IDLE  = 3'd0;
    localparam [2:0] RX_CMD   = 3'd1;
    localparam [2:0] RX_ADDR  = 3'd2;
    localparam [2:0] RX_LEN   = 3'd3;
    localparam [2:0] RX_DATA  = 3'd4;
    localparam [2:0] RX_CHK   = 3'd5;

    localparam integer FRAME_TIMEOUT_CLKS_RAW = (CLK_HZ / 1000) * FRAME_TIMEOUT_MS;
    localparam integer FRAME_TIMEOUT_CLKS     = (FRAME_TIMEOUT_CLKS_RAW < 1) ? 1 : FRAME_TIMEOUT_CLKS_RAW;

    reg [2:0] rx_state_r;
    reg [7:0] rx_cmd_r;
    reg [7:0] rx_addr_r;
    reg [7:0] rx_len_r;
    reg [7:0] rx_chk_xor_r;
    reg [2:0] rx_data_idx_r;
    reg [7:0] rx_payload_r [0:3];
    reg [31:0] rx_timeout_cnt_r;

    reg [7:0] resp_buf_r [0:8];
    reg [3:0] resp_len_r;
    reg [3:0] resp_idx_r;
    reg       resp_active_r;
    reg       tx_issue_hold_r;

    reg        pending_resp_valid_r;
    reg [7:0]  pending_resp_cmd_r;
    reg [7:0]  pending_resp_addr_r;
    reg [7:0]  pending_resp_len_r;
    reg [31:0] pending_resp_data_r;
    reg        pending_resp_use_status_r;
    reg [2:0]  pending_resp_delay_r; // Sửa lên 3-bit để tăng time chờ

    integer i;
    reg [31:0] tmp_wdata_r;
    reg [31:0] tmp_rdata_r;
    reg [7:0]  tmp_len_r;

    function is_valid_addr;
        input [7:0] addr;
        begin
            case (addr)
                ADDR_CTRL,
                ADDR_TWD_MS,
                ADDR_TRST_MS,
                ADDR_ARM_DELAY,
                ADDR_STATUS: is_valid_addr = 1'b1;
                default:     is_valid_addr = 1'b0;
            endcase
        end
    endfunction

    function is_writable_addr;
        input [7:0] addr;
        begin
            case (addr)
                ADDR_CTRL,
                ADDR_TWD_MS,
                ADDR_TRST_MS,
                ADDR_ARM_DELAY: is_writable_addr = 1'b1;
                default:        is_writable_addr = 1'b0;
            endcase
        end
    endfunction

    function [7:0] expected_len;
        input [7:0] addr;
        begin
            case (addr)
                ADDR_CTRL,
                ADDR_TWD_MS,
                ADDR_TRST_MS,
                ADDR_STATUS:    expected_len = 8'd4;
                ADDR_ARM_DELAY: expected_len = 8'd2;
                default:        expected_len = 8'd0;
            endcase
        end
    endfunction

    wire [31:0] status_word_w;

    assign status_word_w = {27'd0, last_kick_src_i, wdo_i, enout_i, fault_active_i, en_effective_i};

    function [31:0] reg_word;
        input [7:0] addr;
        begin
            case (addr)
                ADDR_CTRL:      reg_word = {29'd0, 1'b0, wdi_src_i, en_sw_i};
                ADDR_TWD_MS:    reg_word = twd_ms_i;
                ADDR_TRST_MS:   reg_word = trst_ms_i;
                ADDR_ARM_DELAY: reg_word = {16'd0, arm_delay_us_i};
                ADDR_STATUS:    reg_word = status_word_w;
                default:        reg_word = 32'd0;
            endcase
        end
    endfunction

    task prepare_err_response;
        input [7:0] orig_cmd;
        input [7:0] err_code;
        reg [7:0] chk;
        begin
            chk = CMD_ERR ^ orig_cmd ^ 8'h01 ^ err_code;
            resp_buf_r[0] <= 8'h55;
            resp_buf_r[1] <= CMD_ERR;
            resp_buf_r[2] <= orig_cmd;
            resp_buf_r[3] <= 8'h01;
            resp_buf_r[4] <= err_code;
            resp_buf_r[5] <= chk;
            resp_len_r    <= 4'd6;
            resp_idx_r    <= 4'd0;
            resp_active_r <= 1'b1;
        end
    endtask

    task prepare_ok_response;
        input [7:0]  resp_cmd;
        input [7:0]  resp_addr;
        input [7:0]  resp_len;
        input [31:0] resp_data;
        reg [7:0] chk;
        begin
            chk = resp_cmd ^ resp_addr ^ resp_len;

            resp_buf_r[0] <= 8'h55;
            resp_buf_r[1] <= resp_cmd;
            resp_buf_r[2] <= resp_addr;
            resp_buf_r[3] <= resp_len;

            if (resp_len == 8'd4) begin
                resp_buf_r[4] <= resp_data[31:24];
                resp_buf_r[5] <= resp_data[23:16];
                resp_buf_r[6] <= resp_data[15:8];
                resp_buf_r[7] <= resp_data[7:0];
                chk = chk ^ resp_data[31:24] ^ resp_data[23:16] ^ resp_data[15:8] ^ resp_data[7:0];
                resp_buf_r[8] <= chk;
                resp_len_r    <= 4'd9;
            end else if (resp_len == 8'd2) begin
                resp_buf_r[4] <= resp_data[15:8];
                resp_buf_r[5] <= resp_data[7:0];
                chk = chk ^ resp_data[15:8] ^ resp_data[7:0];
                resp_buf_r[6] <= chk;
                resp_len_r    <= 4'd7;
            end else begin
                resp_buf_r[4] <= chk;
                resp_len_r    <= 4'd5;
            end

            resp_idx_r    <= 4'd0;
            resp_active_r <= 1'b1;
        end
    endtask

    task schedule_ok_response;
        input [7:0]  resp_cmd;
        input [7:0]  resp_addr;
        input [7:0]  resp_len;
        input [31:0] resp_data;
        input        use_status;
        input [2:0]  delay_cycles; // Sửa lên [2:0]
        begin
            pending_resp_cmd_r        <= resp_cmd;
            pending_resp_addr_r       <= resp_addr;
            pending_resp_len_r        <= resp_len;
            pending_resp_data_r       <= resp_data;
            pending_resp_use_status_r <= use_status;
            pending_resp_delay_r      <= delay_cycles;
            pending_resp_valid_r      <= 1'b1;
        end
    endtask

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rx_state_r                <= RX_IDLE;
            rx_cmd_r                  <= 8'd0;
            rx_addr_r                 <= 8'd0;
            rx_len_r                  <= 8'd0;
            rx_chk_xor_r              <= 8'd0;
            rx_data_idx_r             <= 3'd0;
            rx_timeout_cnt_r          <= 32'd0;
            tx_data_o                 <= 8'd0;
            tx_start_o                <= 1'b0;
            wr_en_o                   <= 1'b0;
            wr_addr_o                 <= 8'd0;
            wr_data_o                 <= 32'd0;
            uart_kick_pulse_o         <= 1'b0;
            resp_len_r                <= 4'd0;
            resp_idx_r                <= 4'd0;
            resp_active_r             <= 1'b0;
            tx_issue_hold_r           <= 1'b0;
            pending_resp_valid_r      <= 1'b0;
            pending_resp_cmd_r        <= 8'd0;
            pending_resp_addr_r       <= 8'd0;
            pending_resp_len_r        <= 8'd0;
            pending_resp_data_r       <= 32'd0;
            pending_resp_use_status_r <= 1'b0;
            pending_resp_delay_r      <= 3'd0; // Sửa thành 3'd0
            tmp_wdata_r               <= 32'd0;
            tmp_rdata_r               <= 32'd0;
            tmp_len_r                 <= 8'd0;
            for (i = 0; i < 4; i = i + 1) begin
                rx_payload_r[i] <= 8'd0;
            end
        end else begin
            tx_start_o        <= 1'b0;
            wr_en_o           <= 1'b0;
            uart_kick_pulse_o <= 1'b0;

            if (rx_state_r == RX_IDLE || rx_valid_i || rx_frame_err_i) begin
                rx_timeout_cnt_r <= 32'd0;
            end else if (!resp_active_r && !pending_resp_valid_r) begin
                if (rx_timeout_cnt_r >= (FRAME_TIMEOUT_CLKS - 1)) begin
                    prepare_err_response(rx_cmd_r, ERR_BAD_LEN);
                    rx_state_r       <= RX_IDLE;
                    rx_timeout_cnt_r <= 32'd0;
                end else begin
                    rx_timeout_cnt_r <= rx_timeout_cnt_r + 32'd1;
                end
            end

            if (rx_frame_err_i && !resp_active_r && !pending_resp_valid_r) begin
                prepare_err_response((rx_state_r == RX_IDLE) ? 8'h00 : rx_cmd_r, ERR_UART_FRAME);
                rx_state_r       <= RX_IDLE;
                rx_timeout_cnt_r <= 32'd0;
            end else if (pending_resp_valid_r && !resp_active_r) begin
                if (pending_resp_delay_r != 3'd0) begin
                    pending_resp_delay_r <= pending_resp_delay_r - 3'd1;
                end else begin
                    if (pending_resp_use_status_r) begin
                        prepare_ok_response(
                            pending_resp_cmd_r,
                            pending_resp_addr_r,
                            pending_resp_len_r,
                            status_word_w
                        );
                    end else begin
                        prepare_ok_response(
                            pending_resp_cmd_r,
                            pending_resp_addr_r,
                            pending_resp_len_r,
                            pending_resp_data_r
                        );
                    end
                    pending_resp_valid_r <= 1'b0;
                end
            end else if (!resp_active_r && rx_valid_i) begin
                rx_timeout_cnt_r <= 32'd0;
                case (rx_state_r)
                    RX_IDLE: begin
                        if (rx_data_i == 8'h55) begin
                            rx_state_r    <= RX_CMD;
                            rx_chk_xor_r  <= 8'd0;
                            rx_data_idx_r <= 3'd0;
                        end
                        // Lờ đi các byte rác khi chưa nhận được byte đồng bộ (0x55)
                        // Xóa nhánh else báo ERR_BAD_SYNC ở đây
                    end

                    RX_CMD: begin
                        rx_cmd_r     <= rx_data_i;
                        rx_chk_xor_r <= rx_data_i;
                        rx_state_r   <= RX_ADDR;
                    end

                    RX_ADDR: begin
                        rx_addr_r    <= rx_data_i;
                        rx_chk_xor_r <= rx_chk_xor_r ^ rx_data_i;
                        rx_state_r   <= RX_LEN;
                    end

                    RX_LEN: begin
                        rx_len_r      <= rx_data_i;
                        rx_chk_xor_r  <= rx_chk_xor_r ^ rx_data_i;
                        rx_data_idx_r <= 3'd0;
                        if (rx_data_i == 8'd0) begin
                            rx_state_r <= RX_CHK;
                        end else if (rx_data_i <= 8'd4) begin
                            rx_state_r <= RX_DATA;
                        end else begin
                            prepare_err_response(rx_cmd_r, ERR_BAD_LEN);
                            rx_state_r <= RX_IDLE;
                        end
                    end

                    RX_DATA: begin
                        rx_payload_r[rx_data_idx_r] <= rx_data_i;
                        rx_chk_xor_r                <= rx_chk_xor_r ^ rx_data_i;
                        if (rx_data_idx_r + 3'd1 >= rx_len_r[2:0]) begin
                            rx_state_r <= RX_CHK;
                        end else begin
                            rx_data_idx_r <= rx_data_idx_r + 3'd1;
                        end
                    end

                    RX_CHK: begin
                        if (rx_chk_xor_r != rx_data_i) begin
                            prepare_err_response(rx_cmd_r, ERR_BAD_CHK);
                        end else begin
                            case (rx_cmd_r)
                                CMD_WRITE_REG: begin
                                    if (!is_valid_addr(rx_addr_r)) begin
                                        prepare_err_response(rx_cmd_r, ERR_BAD_ADDR);
                                    end else if (!is_writable_addr(rx_addr_r)) begin
                                        prepare_err_response(rx_cmd_r, ERR_BAD_ACCESS);
                                    end else if (rx_len_r != expected_len(rx_addr_r)) begin
                                        prepare_err_response(rx_cmd_r, ERR_BAD_LEN);
                                    end else begin
                                        tmp_wdata_r = 32'd0;
                                        if (rx_len_r == 8'd4) begin
                                            tmp_wdata_r = {rx_payload_r[0], rx_payload_r[1], rx_payload_r[2], rx_payload_r[3]};
                                        end else if (rx_len_r == 8'd2) begin
                                            tmp_wdata_r = {16'd0, rx_payload_r[0], rx_payload_r[1]};
                                        end

                                        if (((rx_addr_r == ADDR_TWD_MS) || (rx_addr_r == ADDR_TRST_MS)) && (tmp_wdata_r == 32'd0)) begin
                                            prepare_err_response(rx_cmd_r, ERR_BAD_ACCESS);
                                        end else begin
                                            wr_addr_o <= rx_addr_r;
                                            wr_data_o <= tmp_wdata_r;
                                            wr_en_o   <= 1'b1;
                                            // Tăng delay lên 5 chu kỳ để kịp cập nhật STATUS
                                            schedule_ok_response(8'h81, ADDR_STATUS, 8'd4, 32'd0, 1'b1, 3'd5);
                                        end
                                    end
                                end

                                CMD_READ_REG: begin
                                    if (!is_valid_addr(rx_addr_r)) begin
                                        prepare_err_response(rx_cmd_r, ERR_BAD_ADDR);
                                    end else if (!((rx_len_r == 8'd0) || (rx_len_r == expected_len(rx_addr_r)))) begin
                                        prepare_err_response(rx_cmd_r, ERR_BAD_LEN);
                                    end else begin
                                        tmp_rdata_r = reg_word(rx_addr_r);
                                        tmp_len_r   = expected_len(rx_addr_r);
                                        prepare_ok_response(8'h82, rx_addr_r, tmp_len_r, tmp_rdata_r);
                                    end
                                end

                                CMD_KICK: begin
                                    if (rx_len_r != 8'd0) begin
                                        prepare_err_response(rx_cmd_r, ERR_BAD_LEN);
                                    end else if (wdi_src_i != 1'b1) begin
                                        prepare_err_response(rx_cmd_r, ERR_NOT_ALLOW);
                                    end else begin
                                        uart_kick_pulse_o <= 1'b1;
                                        // Tăng delay lên 5 chu kỳ để kịp cập nhật STATUS
                                        schedule_ok_response(8'h83, ADDR_STATUS, 8'd4, 32'd0, 1'b1, 3'd5);
                                    end
                                end

                                CMD_GET_STATUS: begin
                                    if (rx_len_r != 8'd0) begin
                                        prepare_err_response(rx_cmd_r, ERR_BAD_LEN);
                                    end else begin
                                        prepare_ok_response(8'h84, ADDR_STATUS, 8'd4, status_word_w);
                                    end
                                end

                                default: begin
                                    prepare_err_response(rx_cmd_r, ERR_BAD_ACCESS);
                                end
                            endcase
                        end
                        rx_state_r <= RX_IDLE;
                    end

                    default: begin
                        rx_state_r <= RX_IDLE;
                    end
                endcase
            end

            if (tx_issue_hold_r && tx_busy_i) begin
                tx_issue_hold_r <= 1'b0;
            end

            if (resp_active_r && !tx_busy_i && !tx_issue_hold_r) begin
                tx_data_o       <= resp_buf_r[resp_idx_r];
                tx_start_o      <= 1'b1;
                tx_issue_hold_r <= 1'b1;

                if (resp_idx_r + 4'd1 >= resp_len_r) begin
                    resp_idx_r    <= 4'd0;
                    resp_active_r <= 1'b0;
                end else begin
                    resp_idx_r <= resp_idx_r + 4'd1;
                end
            end
        end
    end

endmodule