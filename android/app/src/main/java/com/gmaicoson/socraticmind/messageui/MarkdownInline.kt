package com.gmaicoson.socraticmind.messageui

import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withLink
import androidx.compose.ui.text.withStyle
import com.gmaicoson.socraticmind.chat.markdown.MarkdownRun

@Composable
internal fun MarkdownInline(
    runs: List<MarkdownRun>,
    openLink: (String) -> Unit,
    modifier: Modifier = Modifier,
    level: Int = 0,
    bold: Boolean = false,
    alignment: TextAlign = TextAlign.Start,
) {
    val colors = MaterialTheme.colorScheme
    val annotated =
        buildAnnotatedString {
            for (run in runs) {
                val link = run.link
                val style =
                    SpanStyle(
                        fontWeight = if (run.style.bold || bold) FontWeight.Bold else null,
                        fontStyle = if (run.style.italic) FontStyle.Italic else null,
                        fontFamily = if (run.style.code) FontFamily.Monospace else null,
                        background = if (run.style.code) colors.surfaceContainerHigh else Color.Unspecified,
                        textDecoration =
                            when {
                                run.style.strike && run.link != null -> {
                                    TextDecoration.combine(listOf(TextDecoration.LineThrough, TextDecoration.Underline))
                                }

                                run.style.strike -> {
                                    TextDecoration.LineThrough
                                }

                                else -> {
                                    null
                                }
                            },
                    )
                if (link == null) {
                    withStyle(style) { append(run.text) }
                } else {
                    val linkStyle =
                        TextLinkStyles(SpanStyle(color = colors.primary, textDecoration = TextDecoration.Underline))
                    withLink(LinkAnnotation.Url(link, linkStyle) { openLink(link) }) {
                        withStyle(style) { append(run.text) }
                    }
                }
            }
        }
    val typography = MaterialTheme.typography
    val textStyle =
        when (level) {
            1 -> typography.headlineMedium
            2 -> typography.headlineSmall
            3 -> typography.titleLarge
            4, 5, 6 -> typography.titleMedium
            else -> typography.bodyLarge
        }
    SelectionContainer {
        Text(
            annotated,
            modifier.then(if (level > 0) Modifier.semantics { heading() } else Modifier),
            style = textStyle,
            textAlign = alignment,
        )
    }
}
