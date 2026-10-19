package com.example.ordersystem.product.service;

import com.amazonaws.services.s3.AmazonS3;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.util.ReflectionTestUtils;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class LocalImageStorageTest {
    @Test void browserUrlUsesPublicEndpointAndEncodesFilename() throws Exception {
        var s3 = mock(AmazonS3.class);
        var service = new S3Service(s3);
        ReflectionTestUtils.setField(service, "bucket", "products");
        ReflectionTestUtils.setField(service, "publicBaseUrl", "http://localhost:9000/products/");
        var file = new MockMultipartFile("imageFile", "sample image.png", "image/png", new byte[]{1,2});
        String url = service.uploadFile(file);
        assertTrue(url.startsWith("http://localhost:9000/products/products/"));
        assertTrue(url.endsWith("sample%20image.png"));
        verify(s3).putObject(eq("products"), anyString(), any(java.io.InputStream.class), any(com.amazonaws.services.s3.model.ObjectMetadata.class));
        verify(s3, never()).getUrl(anyString(), anyString());
    }
}
