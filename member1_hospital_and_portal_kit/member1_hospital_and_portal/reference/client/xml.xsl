<?xml version="1.0" encoding="UTF-8"?>
<!-- Stylesheet that turns any of this system's XML definition files into a readable page.
     It uses the same CSS as the portal (app.css) plus xml.css. -->
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="html" encoding="UTF-8" indent="yes" doctype-system="about:legacy-compat"/>

  <xsl:template match="/">
    <html lang="en">
      <head>
        <meta name="viewport" content="width=device-width,initial-scale=1"/>
        <title><xsl:value-of select="name(/*)"/> definition</title>
        <link rel="stylesheet" href="/ui/app.css"/>
        <link rel="stylesheet" href="/ui/xml.css"/>
      </head>
      <body>
        <header class="nav">
          <a class="brand" href="/ui/"><span class="hex"></span><b>Patient Processing System</b></a>
          <div class="who"><a class="btn ghost" href="/xml">All definitions</a></div>
        </header>
        <section class="hero small">
          <div class="wrap">
            <h1>
              <xsl:value-of select="concat(translate(substring(name(/*),1,1),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),substring(name(/*),2))"/>
              <xsl:if test="/*/@name"><xsl:text>: </xsl:text><xsl:value-of select="/*/@name"/></xsl:if>
            </h1>
            <p>This file is a definition the system runs from. Edit it and restart to change behaviour.</p>
          </div>
        </section>
        <div class="wrap pull">
          <section class="card xml">
            <xsl:apply-templates select="/comment() | /*"/>
          </section>
        </div>
        <footer class="foot"><a href="/xml">XML definitions</a><a href="/docs">API documentation</a></footer>
      </body>
    </html>
  </xsl:template>

  <!-- every element becomes a block: tag name, attributes as chips, children nested below -->
  <xsl:template match="*">
    <div class="x-node">
      <div class="x-head">
        <span class="x-tag t-{name()}"><xsl:value-of select="name()"/></span>
        <xsl:for-each select="@*">
          <span class="x-attr"><b><xsl:value-of select="name()"/></b><xsl:value-of select="."/></span>
        </xsl:for-each>
      </div>
      <xsl:if test="* or comment()">
        <div class="x-body"><xsl:apply-templates select="* | comment()"/></div>
      </xsl:if>
    </div>
  </xsl:template>

  <xsl:template match="comment()">
    <p class="x-note"><xsl:value-of select="normalize-space(.)"/></p>
  </xsl:template>
</xsl:stylesheet>
