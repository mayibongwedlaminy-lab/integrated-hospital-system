package pps.lab;

/** An answer that is not 200: carries the status and the text sent back as {"detail": ...}. */
final class HttpError extends RuntimeException {
    final int status;
    final String detail;

    HttpError(int status, String detail) {
        super(detail);
        this.status = status;
        this.detail = detail;
    }
}
