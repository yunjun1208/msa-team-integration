package com.example.ordersystem.product.service;

import com.amazonaws.services.s3.AmazonS3;
import com.amazonaws.services.s3.model.ObjectMetadata;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.UUID;

@Service
@RequiredArgsConstructor
public class S3Service {

    private final AmazonS3 amazonS3;

    @Value("${cloud.aws.s3.bucket}")
    private String bucket;

    @Value("${cloud.aws.s3.public-base-url:}")
    private String publicBaseUrl;

    public String uploadFile(MultipartFile file) throws IOException {
        String fileName = "products/" + UUID.randomUUID() + "_" + file.getOriginalFilename();

        ObjectMetadata metadata = new ObjectMetadata();
        metadata.setContentLength(file.getSize());
        metadata.setContentType(file.getContentType());

        try (var input = file.getInputStream()) {
            amazonS3.putObject(bucket, fileName, input, metadata);
        }

        if (!publicBaseUrl.isBlank()) {
            return publicBaseUrl.replaceAll("/+$", "") + "/" + org.springframework.web.util.UriUtils.encodePath(fileName, java.nio.charset.StandardCharsets.UTF_8);
        }
        return amazonS3.getUrl(bucket, fileName).toString();
    }
}
